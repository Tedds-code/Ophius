"""Explicit profile-aware medication guards; never infer allergy from history alone."""
from copy import deepcopy
import json
from pathlib import Path
import re
import unicodedata


def normalized(value):
    text = unicodedata.normalize('NFKD', str(value)).lower()
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', text).split())


class AllergyGuard:
    def __init__(self, path=None):
        path = Path(path) if path else Path(__file__).resolve().parents[1]/'config'/'medication_allergens.json'
        self.catalog = json.loads(path.read_text(encoding='utf-8'))
        self.aliases = {normalized(k): normalized(v) for k,v in self.catalog['aliases'].items()}
        self.families = {normalized(k): {normalized(x) for x in values} for k, values in self.catalog['families'].items()}
        self.known = {normalized(x) for x in self.catalog['known_ingredients']}
        self.known.update(x for members in self.families.values() for x in members)
        self.uncertain = {normalized(k): {normalized(x) for x in v} for k,v in self.catalog['uncertain_related_families'].items()}

    def canonical(self, value):
        word = normalized(value)
        return self.aliases.get(word, word)

    def allergies(self, profile):
        values = profile.get('medical_history', {}).get('allergies')
        if values is None:
            return [], True
        unknown = any(normalized(x) in {'unknown', 'not known', 'not supplied', 'unassessed'} for x in values)
        empty = {'none', 'no known allergies', 'no known drug allergies', 'nkda', ''}
        return [str(x) for x in values if normalized(x) not in empty], unknown

    def family(self, ingredient):
        return {family for family, members in self.families.items()
                if ingredient == family or ingredient in members or
                any((' '+member+' ') in (' '+ingredient+' ') for member in members)}

    def check(self, profile, medication):
        if not isinstance(medication, str) or not medication.strip() or len(medication) > 160:
            raise ValueError('Enter a single active ingredient, up to 160 characters')
        ingredient = self.canonical(medication)
        allergies, unknown = self.allergies(profile)
        unmapped = [a for a in allergies if self.canonical(a) not in self.known and self.canonical(a) not in self.families]
        matches, uncertain = [], []
        for original in allergies:
            allergen = self.canonical(original)
            exact = ingredient == allergen or (' '+allergen+' ') in (' '+ingredient+' ')
            if exact or self.family(ingredient) & self.family(allergen):
                matches.append(original)
            if any(ingredient in self.uncertain.get(family, set()) for family in self.family(allergen)):
                uncertain.append(original)
        if matches:
            status, reason = 'blocked', 'Recorded allergy match: '+', '.join(matches)
        elif unknown:
            status, reason = 'needs_review', 'Allergy history is unknown; review before medication use'
        elif uncertain:
            status, reason = 'needs_review', 'Related-drug allergy requires individual review: '+', '.join(uncertain)
        elif unmapped:
            status, reason = 'needs_review', 'Recorded allergy notation is not mapped in the configured catalog: '+', '.join(unmapped)
        elif ingredient not in self.known:
            status, reason = 'needs_review', 'Active ingredient is not identified in the configured medication catalog'
        else:
            status, reason = 'no_recorded_match', 'No recorded allergy match; other contraindications and clinician review still apply'
        return {'medication': medication.strip(), 'ingredient': ingredient, 'status': status,
                'blocked': status == 'blocked', 'recording_allowed': status == 'no_recorded_match',
                'matched_allergies': matches, 'reason': reason, 'allergies': allergies}

    def exposure_matches(self, profile, exposures):
        return [{'exposure': exposure, **self.check(profile, exposure)} for exposure in exposures
                if self.check(profile, exposure)['blocked']]

    def treatment(self, profile, treatment):
        result = deepcopy(treatment)
        text = ' '.join([result.get('treatment_name',''), *result.get('instructions',[]), result.get('dosage','')])
        words = ' '+normalized(text)+' '
        profile_names = {self.canonical(name) for name in self.allergies(profile)[0]}
        names = sorted({self.canonical(name) for name in self.known | self.aliases.keys() | profile_names
                        if (' '+name+' ') in words})
        checks = [self.check(profile, name) for name in names]
        non_drug = 'non pharmacological' in normalized(result.get('dosage',''))
        avoidance = normalized(result.get('treatment_name','')).startswith('avoid ')
        generic_drug = bool(re.search(r'\b(antibiotic|antibiotics|analgesic|analgesics|antihistamine|antihistamines|sedative|sedation|medication|corticosteroid|antiemetic|anticoagulant)\b', normalized(text)))
        blocked = [c for c in checks if c['blocked']]
        review = [c for c in checks if c['status'] == 'needs_review']
        status = 'avoidance_guidance' if avoidance else 'non_drug' if non_drug else 'blocked' if blocked else 'needs_review' if review or (generic_drug and not names) else 'no_recorded_match' if names else 'reference_only'
        result['allergy_safety'] = {'status':status, 'checks':checks, 'recorded_allergies':self.allergies(profile)[0],
            'restricted':status in {'blocked','needs_review'},
            'reason': '; '.join(c['reason'] for c in blocked or review) if blocked or review else
                'Specific ingredient and allergy review required' if status == 'needs_review' else
                'Reference information; no automatic medication administration'}
        if result['allergy_safety']['restricted']:
            result['instructions'] = []
            result['dosage'] = 'Withheld: '+result['allergy_safety']['reason']
        return result

    def finding(self, profile, finding):
        result = deepcopy(finding)
        result['treatments'] = [self.treatment(profile, item) for item in result.get('treatments', [])]
        result['recorded_allergies'] = self.allergies(profile)[0]
        return result
