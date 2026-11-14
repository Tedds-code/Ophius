# Made in cooperation with ChatGPT
"""Add body-temperature/manual cardiovascular and symptom tests safely to fixed_tests.py.

Existing skin thermistor readings stay separate: measuring skin does NOT imply core temp.
"""
from pathlib import Path
import shutil
import sys

CATALOG = Path('src/astro_health/fixed_tests.py')
MARKER = '# V10 ADDITIONAL TESTS - START'
BLOCK = "\n# V10 ADDITIONAL TESTS - START\n# New manual tests: temperature is BODY temperature; thermistor skin sensor remains separate.\nFIXED_TESTS += (\n    FixedTest('temperature', 'Body temperature (manual)', (TestField('temperature', 'Body temperature', 'degC'),)),\n    FixedTest('qtc_interval_male', 'QTc (male reference)', (TestField('qtc_interval_male', 'QTc', 'ms'),)),\n    FixedTest('qtc_interval_female', 'QTc (female reference)', (TestField('qtc_interval_female', 'QTc', 'ms'),)),\n    FixedTest('vomiting_episodes', 'Vomiting episodes', (TestField('vomiting_episodes', 'Episodes', 'episodes'),)),\n    FixedTest('space_motion_sickness_duration_hours', 'Space motion sickness duration', (TestField('space_motion_sickness_duration_hours', 'Duration', 'hours'),)),\n    FixedTest('nasal_congestion_duration_hours', 'Nasal congestion duration', (TestField('nasal_congestion_duration_hours', 'Duration', 'hours'),)),\n    FixedTest('urinary_incontinence_duration_hours', 'Urinary incontinence duration', (TestField('urinary_incontinence_duration_hours', 'Duration', 'hours'),)),\n    FixedTest('urinary_retention_duration_hours', 'Urinary retention duration', (TestField('urinary_retention_duration_hours', 'Duration', 'hours'),)),\n    FixedTest('cardiovascular_disease_risk_dose', 'Cumulative Dose to Heart (Pathogenesis Threshold)', (TestField('cardiovascular_disease_risk_dose', 'Cumulative Dose to Heart (Pathogenesis Threshold)', 'Gy-eq'),)),\n    FixedTest('circulatory_dose_30d', 'Dose to circulatory system (heart muscle and nearby arteries) - 30 days', (TestField('circulatory_dose_30d', 'Dose to circulatory system (heart muscle and nearby arteries) - 30 days', 'mGy-Eq'),)),\n    FixedTest('circulatory_dose_1y', 'Dose to circulatory system (heart muscle and nearby arteries) - 1 year', (TestField('circulatory_dose_1y', 'Dose to circulatory system (heart muscle and nearby arteries) - 1 year', 'mGy-Eq'),)),\n    FixedTest('circulatory_dose_career', 'Dose to circulatory system (heart muscle and nearby arteries) - career', (TestField('circulatory_dose_career', 'Dose to circulatory system (heart muscle and nearby arteries) - career', 'mGy-Eq'),)),\n    FixedTest('cns_dose_30d', 'Dose to central nervous system (hippocampus) - 30 days', (TestField('cns_dose_30d', 'Dose to central nervous system (hippocampus) - 30 days', 'mGy'),)),\n    FixedTest('cns_dose_1y', 'Dose to central nervous system (hippocampus) - 1 year', (TestField('cns_dose_1y', 'Dose to central nervous system (hippocampus) - 1 year', 'mGy'),)),\n    FixedTest('cns_dose_career', 'Dose to central nervous system (hippocampus) - career', (TestField('cns_dose_career', 'Dose to central nervous system (hippocampus) - career', 'mGy'),)),\n    FixedTest('cns_hze_dose_1y', 'Dose to CNS from heavy ions Z>=10 - 1 year', (TestField('cns_hze_dose_1y', 'Dose to CNS from heavy ions Z>=10 - 1 year', 'mGy'),)),\n    FixedTest('cns_hze_dose_career', 'Dose to CNS from heavy ions Z>=10 - career', (TestField('cns_hze_dose_career', 'Dose to CNS from heavy ions Z>=10 - career', 'mGy'),)),\n)\n# V10 ADDITIONAL TESTS - END\n"

def main():
    if not CATALOG.is_file():
        sys.exit(f'Run from your repository root: missing {CATALOG}')
    text = CATALOG.read_text(encoding='utf-8')
    if MARKER in text:
        print('V10 test catalog already installed; no changes made')
        return
    anchor = 'TESTS_BY_ID ='
    if anchor not in text or 'FIXED_TESTS:' not in text:
        sys.exit('Catalog format differs; no changes made, please provide current fixed_tests.py')
    backup = CATALOG.with_suffix('.py.v10.bak')
    shutil.copy2(CATALOG, backup)
    text = text.replace(anchor, BLOCK + '\n' + anchor, 1)
    CATALOG.write_text(text, encoding='utf-8')
    print(f'Extended catalog; backup: {backup}')

if __name__ == '__main__':
    main()
