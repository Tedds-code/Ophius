"""Rule + threshold engine.

Everything numeric and every diagnostic rule is read from the two JSON files in
``data/`` (thresholds.json, diagnostic_rules.json). Nothing medical is hard-coded
here except a few documented *policy* constants (see below).

Output is decision support only: suspicion / alert levels, never a diagnosis.
"""
from __future__ import annotations

import json
import math
import re
from copy import deepcopy
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "config"

LEVEL_PRIORITY = {"MONITOR": 1, "SUSPECTED": 2, "URGENT": 3, "EMERGENCY": 4}
CHANNEL_LEVELS = ("ENVIRONMENT_ALERT", "TEAM_SUPPORT")

# --- Policy constants (software decisions, NOT taken from the NASA sources) -----------
# Source sheet: a red flag "excludes the benign classification and requires medical
# evaluation" but defines no alert level. We surface it at this level.
RED_FLAG_MIN_LEVEL = "URGENT"

# Boundary semantics. Default: "above" means value > limit, "below" means value < limit.
# These limits are *inclusive* because the sources say normal is strictly under them
# (BP "<120/<80") or the condition cut-off is ">= 110 bpm" (MTWA / dysrhythmia risk).
INCLUSIVE_LIMITS = {
    ("heart_rate", "critical_above"),
    ("blood_pressure_systolic", "caution_above"),
    ("blood_pressure_diastolic", "caution_above"),
}

# (primary, secondary): drop `secondary` when `primary` is active at an equal or higher
# level. Implements the overlap notes in the rules file (one event code, not two).
SUPERSEDES = [
    ("C02", "C01"),
    ("C02", "C23"),
    ("C05", "C25"),
    ("C06", "C25"),
    ("C04", "C15"),
]

OPERATORS = {
    "gte": lambda a, b: a >= b,
    "gt": lambda a, b: a > b,
    "lte": lambda a, b: a <= b,
    "lt": lambda a, b: a < b,
}


def finite_number(value) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        return False


def validate_profile(profile: dict) -> dict:
    """Validate a baseline document and return a defensive copy, preserving fields."""
    if not isinstance(profile, dict):
        raise ValueError("Profile must be a JSON object")
    identifier = profile.get("astronaut_id")
    if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", identifier):
        raise ValueError("astronaut_id must be a short identifier containing letters, digits, dot, underscore or hyphen")
    personal = profile.get("personal_information")
    if not isinstance(personal, dict) or personal.get("gender") not in ("male", "female"):
        raise ValueError("personal_information.gender must be male or female for the supplied reference bands")
    for key in ("age", "weight_kg", "height_cm"):
        if key in personal and (not finite_number(personal[key]) or personal[key] <= 0):
            raise ValueError(f"personal_information.{key} must be a positive finite number")
    mission = profile.get("mission_details")
    duration = mission.get("duration_days") if isinstance(mission, dict) else None
    if not isinstance(duration, int) or isinstance(duration, bool) or duration <= 0:
        raise ValueError("mission_details.duration_days must be a positive integer")
    baseline = profile.get("pre_flight_baseline")
    if not isinstance(baseline, dict):
        raise ValueError("pre_flight_baseline must be an object")
    allergies = profile.get('medical_history', {}).get('allergies', [])
    if not isinstance(allergies, list) or any(not isinstance(x, str) or not x.strip() or len(x) > 160 for x in allergies):
        raise ValueError('medical_history.allergies must be a list of nonempty names')

    def walk(node, path):
        if isinstance(node, dict):
            if "value" in node:
                if not finite_number(node["value"]) or node["value"] < 0:
                    raise ValueError(f"{path}.value must be a nonnegative finite number")
                if not isinstance(node.get("unit"), str) or not node["unit"].strip():
                    raise ValueError(f"{path}.unit is required")
            for key, value in node.items():
                if key == "date":
                    if not isinstance(value, str):
                        raise ValueError(f"{path}.date must be an ISO timestamp")
                    try:
                        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                        if parsed.tzinfo is None:
                            raise ValueError("timezone required")
                    except ValueError as exc:
                        raise ValueError(f"{path}.date must include a timezone") from exc
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for value in node:
                walk(value, path)
        elif isinstance(node, float) and not math.isfinite(node):
            raise ValueError(f"{path} must be finite")

    walk(profile, "profile")
    return deepcopy(profile)


def baseline_readings(profile: dict) -> dict:
    """Flatten known baseline fields without making them live observations."""
    baseline = profile.get("pre_flight_baseline", {})
    out = {}

    def add(key, item, timestamp=None):
        if isinstance(item, dict) and finite_number(item.get("value")) and isinstance(item.get("unit"), str):
            out[key] = {"value": item["value"], "unit": item["unit"], "timestamp": timestamp}

    labs = baseline.get("blood_tests", {})
    for group in ("cbc", "coagulation", "chemistry"):
        for key, item in labs.get(group, {}).items():
            add(key, item, labs.get("date"))
    cardio = baseline.get("cardiovascular", {})
    timestamp = cardio.get("date")
    for source, key in (("heart_rate_resting", "heart_rate"), ("spo2_resting", "spo2")):
        add(key, cardio.get(source), timestamp)
    bp = cardio.get("blood_pressure_resting", {})
    for component in ("systolic", "diastolic"):
        add("blood_pressure_" + component, {"value": bp.get(component), "unit": bp.get("unit")}, timestamp)
    ecg = cardio.get("ecg_baseline", {})
    for key in ("qtc_interval", "pr_interval", "qrs_duration"):
        add(key, ecg.get(key), timestamp)
    hrv = cardio.get("hrv", {})
    add("hrv_rmssd", {"value": hrv.get("rmssd"), "unit": hrv.get("unit")}, timestamp)
    radiation = baseline.get("radiation_exposure", {})
    add("cumulative_effective_dose", radiation.get("career_effective_dose_start"), radiation.get("date"))
    return out


@dataclass
class Case:
    """One astronaut at one moment: what the sensors read and what they reported."""

    sex: str = "male"
    symptoms: set = field(default_factory=set)
    context: set = field(default_factory=set)
    # generic keys (e.g. "hemoglobin", not "hemoglobin_male") + derived signals
    readings: dict = field(default_factory=dict)
    mission_duration_days: int = 180


class KnowledgeBase:
    def __init__(self, thresholds_path: Optional[Path] = None, rules_path: Optional[Path] = None,
                 treatment_path: Optional[Path] = None):
        self.thresholds = json.loads(Path(thresholds_path or DATA_DIR / "thresholds.json").read_text("utf-8"))
        self.rules_doc = json.loads(Path(rules_path or DATA_DIR / "diagnostic_rules.json").read_text("utf-8"))
        self.signals: dict = self.thresholds["signals"]
        self.cutoffs: list = self.thresholds.get("condition_cutoffs", [])
        self.rules: list = self.rules_doc["diagnostic_rules"]
        self.rules_by_id = {r["id"]: r for r in self.rules}
        self.vocab = self.rules_doc["input_vocabulary"]
        self.alert_levels = {a["id"]: a for a in self.rules_doc["alert_levels"]}
        self.sex_bases = {k[: -len("_male")] for k in self.signals if k.endswith("_male")}
        self.derived = deepcopy(self.vocab["derived_signals"])
        for cutoff in self.cutoffs:
            key = cutoff.get('signal')
            if key and key != 'mission_day' and key not in self.signals:
                self.derived.setdefault(key, {'label': 'Symptom duration' if key == 'symptom_duration_hours' else key,
                    'description': 'Manually reported measurement used by a configured condition cutoff',
                    'unit': cutoff.get('unit', '')})
        self.treatment_catalog = json.loads(Path(treatment_path or DATA_DIR / "treatment.json").read_text("utf-8"))
        self.treatments_by_id = {entry["condition_id"]: entry for entry in self.treatment_catalog}
        if len(self.treatments_by_id) != len(self.treatment_catalog):
            raise ValueError("Duplicate treatment condition identifier")

    def treatment_for(self, key: str) -> list[dict]:
        """Return the supplied reference entries, without inferring indication logic."""
        entry = self.treatments_by_id.get(key)
        return deepcopy(entry.get("treatments", [])) if entry else []

    # ------------------------------------------------------------------ signals
    def signal_name(self, base: str, sex: str) -> Optional[str]:
        """Generic reading key -> thresholds.json signal name for this sex."""
        if base in self.sex_bases:
            return f"{base}_{sex}"
        return base if base in self.signals else None

    def base_name(self, name: str) -> tuple[str, Optional[str]]:
        """thresholds.json / rules signal name -> (generic key, sex or None)."""
        for sx in ("male", "female"):
            suf = f"_{sx}"
            if name.endswith(suf) and name[: -len(suf)] in self.sex_bases:
                return name[: -len(suf)], sx
        return name, None

    def reading_keys(self) -> list[dict]:
        """Generic measurement schema (one entry per base signal)."""
        out, seen = [], set()
        for name, sig in self.signals.items():
            base, sx = self.base_name(name)
            if base in seen:
                continue
            seen.add(base)
            label = sig["label"]
            if sx:
                label = label.replace(" - Male", "").replace(" - Female", "")
            out.append({"key": base, "label": label, "unit": sig["unit"], "category": sig["category"],
                        "sex_specific": sx is not None})
        return out

    def limits_for(self, name: str, case: Case) -> dict:
        sig = self.signals[name]
        limits = {k: sig.get(k) for k in ("caution_below", "caution_above", "critical_below", "critical_above")}
        if sig.get("scales_with_mission_duration") and limits.get("critical_above") is not None:
            # NASA-STD-3001 V1 4032: limit is per mission year (6-month mission -> 10 mSv)
            limits["critical_above"] = round(limits["critical_above"] * case.mission_duration_days / 365.0, 2)
        return limits

    def _cmp(self, name: str, level: str, value, limits: Optional[dict] = None) -> bool:
        limits = limits or self.signals.get(name, {})
        limit = limits.get(level)
        if limit is None or not finite_number(value):
            return False
        if level.endswith("_above"):
            return value >= limit if (name, level) in INCLUSIVE_LIMITS else value > limit
        return value < limit

    def classify(self, name: str, value, limits: dict) -> str:
        if not finite_number(value):
            return "invalid"
        if self._cmp(name, "critical_above", value, limits) or self._cmp(name, "critical_below", value, limits):
            return "critical"
        if self._cmp(name, "caution_above", value, limits) or self._cmp(name, "caution_below", value, limits):
            return "caution"
        return "normal"

    @staticmethod
    def display_scale(limits: dict, unit: str) -> list[float]:
        lows = [v for k, v in limits.items() if k.endswith("_below") and v is not None]
        highs = [v for k, v in limits.items() if k.endswith("_above") and v is not None]
        if lows and highs:
            span = max(highs) - min(lows)
            return [round(min(lows) - span * 0.4, 3), round(max(highs) + span * 0.4, 3)]
        if highs:
            return [0, round(max(highs) * 1.35, 3)]
        if lows:
            top = 100 if unit == "%" else min(lows) * 1.25
            return [round(min(lows) * 0.85, 3), top]
        return [0, 1]

    def evaluate_signals(self, case: Case) -> list[dict]:
        out = []
        for base, value in case.readings.items():
            name = self.signal_name(base, case.sex)
            if name is None or value is None:
                continue
            sig = self.signals[name]
            limits = self.limits_for(name, case)
            out.append({
                "key": base, "name": name,
                "label": sig["label"].replace(" - Male", "").replace(" - Female", ""),
                "category": sig["category"], "unit": sig["unit"], "value": value if finite_number(value) else None,
                "status": self.classify(name, value, limits),
                "limits": limits, "window": sig.get("window"),
                "scale": self.display_scale(limits, sig["unit"]),
                "source": (sig.get("source") or {}).get("document") or (sig.get("source") or {}).get("type"),
                "source_url": (sig.get("source") or {}).get("url"),
            })
        return out

    # -------------------------------------------------------------- expressions
    def _value(self, name: str, case: Case):
        base, sx = self.base_name(name)
        if sx is not None and sx != case.sex:
            return None  # e.g. qtc_interval_male for a female astronaut
        return case.readings.get(base)

    def _truth(self, expr: dict, case: Case, ignore_not: bool = False) -> Optional[bool]:
        """Kleene three-valued logic: absence of a measurement is unknown.

        In particular, NOT(missing measurement) is unknown, never evidence for
        a benign condition. A sex-inapplicable band is false, not missing.
        """
        if "all" in expr:
            values = [self._truth(e, case, ignore_not) for e in expr["all"]]
            return False if False in values else (None if None in values else True)
        if "any" in expr:
            values = [self._truth(e, case, ignore_not) for e in expr["any"]]
            return True if True in values else (None if None in values else False)
        if "not" in expr:
            if ignore_not:
                return True
            value = self._truth(expr["not"], case, ignore_not)
            return None if value is None else not value
        if "at_least" in expr:
            spec = expr["at_least"]
            values = [self._truth(e, case, ignore_not) for e in spec["of"]]
            actual = sum(v is True for v in values)
            possible = actual + sum(v is None for v in values)
            return True if actual >= spec["n"] else (False if possible < spec["n"] else None)
        if "symptom" in expr:
            return expr["symptom"] in case.symptoms
        if "context" in expr:
            return expr["context"] in case.context
        if "signal" in expr:
            _, sex = self.base_name(expr["signal"])
            if sex is not None and sex != case.sex:
                return False
            value = self._value(expr["signal"], case)
            if not finite_number(value):
                return None
            if "level" in expr:
                name = expr["signal"]
                if name not in self.signals:
                    raise ValueError(f"Unknown signal in rule: {name}")
                return self._cmp(name, expr["level"], value, self.limits_for(name, case))
            op = expr.get("operator")
            if op in OPERATORS:
                return OPERATORS[op](value, expr["value"])
            if op == "between":
                lo, hi = expr["value"]
                return lo <= value <= hi
        raise ValueError(f"Unknown expression node: {expr}")

    def ev(self, expr: dict, case: Case, ignore_not: bool = False) -> bool:
        return self._truth(expr, case, ignore_not) is True

    def matches(self, expr: dict, case: Case) -> list[dict]:
        """Leaves that are true and contributed to a satisfied expression (for explanations)."""
        if "all" in expr:
            return [m for e in expr["all"] for m in self.matches(e, case)]
        if "any" in expr:
            return [m for e in expr["any"] if self.ev(e, case) for m in self.matches(e, case)]
        if "at_least" in expr:
            return [m for e in expr["at_least"]["of"] if self.ev(e, case) for m in self.matches(e, case)]
        if "not" in expr:
            return []
        if not self.ev(expr, case):
            return []
        if "symptom" in expr:
            return [{"kind": "symptom", "id": expr["symptom"]}]
        if "context" in expr:
            return [{"kind": "context", "id": expr["context"]}]
        base, _ = self.base_name(expr["signal"])
        return [{"kind": "signal", "key": base, "value": self._value(expr["signal"], case),
                 "level": expr.get("level"), "operator": expr.get("operator"), "limit": expr.get("value")}]

    # -------------------------------------------------------------------- rules
    def _marker_active(self, marker: dict, case: Case) -> bool:
        name = marker["signal"]
        value = self._value(name, case)
        if not finite_number(value):
            return False
        if "level" in marker:
            return name in self.signals and self._cmp(name, marker["level"], value, self.limits_for(name, case))
        op = marker.get("operator")
        return op in OPERATORS and OPERATORS[op](value, marker["value"])

    def evaluate_rule(self, rule: dict, case: Case) -> dict:
        triggered = [lvl for lvl, expr in rule["levels"].items() if self.ev(expr, case)]
        numeric = [l for l in triggered if l in LEVEL_PRIORITY]
        channels = [l for l in triggered if l in CHANNEL_LEVELS]
        primary = max(numeric, key=LEVEL_PRIORITY.get) if numeric else None

        red = False
        rf = rule.get("red_flags")
        if rf:
            if primary is not None:
                active = True
            else:  # would the benign classification have applied had no red flag been present?
                base_levels = sorted(
                    (l for l in rule["levels"] if l in LEVEL_PRIORITY), key=LEVEL_PRIORITY.get)
                active = bool(base_levels) and self.ev(rule["levels"][base_levels[0]], case, ignore_not=True)
            red = active and self.ev(rf["expression"], case)

        level = primary
        red_only = False
        if red:
            if primary is None:
                level, red_only = RED_FLAG_MIN_LEVEL, True
            elif LEVEL_PRIORITY[primary] < LEVEL_PRIORITY[RED_FLAG_MIN_LEVEL]:
                level = RED_FLAG_MIN_LEVEL
        return {"rule": rule, "triggered": triggered, "primary": primary, "level": level,
                "channels": channels, "red_flag": red, "red_flag_only": red_only}

    def _qt_warnings(self, rule: dict, case: Case) -> list[dict]:
        warns = []
        for sig_name in rule.get("medication", {}).get("qt_check_signals", []) or []:
            base, sx = self.base_name(sig_name)
            if sx != case.sex:
                continue
            value = case.readings.get(base)
            if value is None:
                warns.append({"code": "qt_missing"})
            else:
                status = self.classify(sig_name, value, self.limits_for(sig_name, case))
                if status != "normal":
                    warns.append({"code": f"qt_{status}", "value": value})
        return warns

    def build_finding(self, res: dict, case: Case) -> dict:
        rule = res["rule"]
        expr_level = res["primary"] or (res["channels"][0] if res["channels"] else None)
        evidence = self.matches(rule["levels"][expr_level], case) if expr_level else []
        if res["red_flag_only"]:
            evidence = self.matches(rule["red_flags"]["expression"], case)
        support = None
        if rule.get("supporting_evidence"):
            support = self.ev(rule["supporting_evidence"], case)
        markers = [m for m in rule.get("severity_markers", []) if self._marker_active(m, case)]
        window = (rule.get("timing") or {}).get("typical_window")
        in_window = None
        if window and window.get("unit") == "mission_day" and case.readings.get("mission_day") is not None:
            lo, hi = window["range"]
            in_window = lo <= case.readings["mission_day"] <= hi
        med = rule.get("medication") or {}
        display_level = res["level"] or (res["channels"][0] if res["channels"] else None)

        # An escalation level (e.g. "syncope -> EMERGENCY" inside the diarrhea rule) can fire without the
        # rule's base condition. Flag it so the UI says "warning sign related to X", not "you have X".
        escalation_only = False
        esc = rule.get("escalation")
        if esc and res["primary"] == esc.get("level") and not res["red_flag"]:
            lows = sorted((l for l in rule["levels"] if l in LEVEL_PRIORITY and l != esc["level"]),
                          key=LEVEL_PRIORITY.get)
            if lows:
                escalation_only = not self.ev(rule["levels"][lows[0]], case)
        # Self-care steps written for a benign MONITOR-level condition must not be shown for a warning sign.
        hide_therapy = res["red_flag_only"] or ((res["red_flag"] or escalation_only) and rule.get("default_level") == "MONITOR")
        finding = {
            "rule_id": rule["id"], "condition_id": rule["condition_id"], "name": rule["name"],
            "group": rule["group"], "level": display_level, "numeric_level": res["level"],
            "channels": res["channels"], "red_flag": res["red_flag"], "red_flag_only": res["red_flag_only"],
            "red_flag_text": (rule.get("red_flags") or {}).get("description") if res["red_flag"] else None,
            "evidence": evidence, "supporting_evidence_met": support,
            "severity_markers": [m["meaning"] for m in markers],
            "escalation": rule.get("escalation"),
            "escalation_only": escalation_only, "hide_therapy": hide_therapy,
            "steps": [] if hide_therapy else rule.get("recommended_steps", []),
            "medication": {
                "summary": med.get("summary"), "specific_dose": med.get("specific_dose"),
                "requires_mission_sop": med.get("requires_mission_sop", True),
                "warnings": self._qt_warnings(rule, case),
            },
            "do_not": rule.get("do_not", []), "kit": rule.get("medical_kit", []),
            "confirmation": rule.get("confirmation", []),
            "timing": {"description": (rule.get("timing") or {}).get("description"), "in_typical_window": in_window},
            "incidence": (rule.get("incidence") or {}).get("summary"),
            "limitations": rule.get("limitations"),
            "source": rule.get("source"),
            "privacy_sensitive": bool((rule.get("data_handling") or {}).get("privacy_sensitive")),
            "logic": rule.get("logic_description"),
        }
        catalog_key = rule["id"] if rule["id"] in self.treatments_by_id else rule["condition_id"]
        finding["treatments"] = [] if hide_therapy else self.treatment_for(catalog_key)
        finding["treatment_source"] = "treatment.json" if catalog_key in self.treatments_by_id else None
        # Detailed treatment information comes from the updated catalog. The
        # diagnostic file still supplies contraindications and escalation.
        if finding["treatment_source"]:
            finding["steps"] = []
            finding["medication"]["summary"] = None
            finding["medication"]["specific_dose"] = None
        return finding

    # ------------------------------------------------------------------ assess
    def assess(self, case: Case) -> dict:
        if case.sex not in ("male", "female"):
            raise ValueError("Case sex must be male or female for the supplied reference bands")
        signals = self.evaluate_signals(case)
        results = [self.evaluate_rule(r, case) for r in self.rules]
        active = {r["rule"]["id"]: r for r in results if r["level"] or r["channels"]}

        for primary, secondary in SUPERSEDES:
            if primary in active and secondary in active:
                p, s = active[primary]["level"], active[secondary]["level"]
                if s is not None and p is not None and LEVEL_PRIORITY[s] <= LEVEL_PRIORITY[p]:
                    del active[secondary]

        findings = [self.build_finding(r, case) for r in active.values()]
        qt = next((s for s in signals if s["key"] == "qtc_interval" and s["status"] in ("caution", "critical")), None)
        if qt:
            level = "URGENT" if qt["status"] == "critical" else "MONITOR"
            findings.append({
                "rule_id": "QTC", "condition_id": "qtc_interval_prolongation",
                "name": "QTc prolongation", "group": "Cardiovascular", "level": level,
                "numeric_level": level, "channels": [], "red_flag": False,
                "red_flag_only": False, "escalation_only": False, "hide_therapy": False,
                "evidence": [{"kind": "signal", "key": "qtc_interval", "value": qt["value"], "unit": "ms"}],
                "treatments": self.treatment_for("qtc_interval_prolongation"),
                "treatment_source": "treatment.json", "steps": [], "do_not": [],
                "confirmation": ["Review ECG and device signal quality."],
                "medication": {"summary": None, "specific_dose": None, "warnings": [], "requires_mission_sop": True},
                "privacy_sensitive": False,
                "logic": "QTc exceeds the applicable sex-specific configured threshold.",
            })

        def sort_key(f):
            if f["numeric_level"]:
                prio = LEVEL_PRIORITY[f["numeric_level"]]
            else:
                prio = 3.5 if "ENVIRONMENT_ALERT" in f["channels"] else 0.5
            return (-prio, f["rule_id"])

        findings.sort(key=sort_key)

        info = []
        hr = case.readings.get("heart_rate")
        for c in self.cutoffs:
            if c["signal"] == "heart_rate" and finite_number(hr) and OPERATORS[c["operator"]](hr, c["value"]):
                info.append({"id": c["condition_id"], "value": hr, "unit": c["unit"], "note": c.get("note")})

        levels = [f["numeric_level"] for f in findings if f["numeric_level"]]
        top = max(levels, key=LEVEL_PRIORITY.get) if levels else None
        any_crit = any(s["status"] == "critical" for s in signals)
        any_caut = any(s["status"] == "caution" for s in signals)
        if top == "EMERGENCY":
            overall = "EMERGENCY"
        elif top == "URGENT" or any_crit:
            overall = "URGENT"
        elif top == "SUSPECTED":
            overall = "SUSPECTED"
        elif top == "MONITOR" or any_caut or info:
            overall = "MONITOR"
        else:
            overall = "NORMAL" if signals and all(s["status"] == "normal" for s in signals) else "UNKNOWN"
        return {
            "overall": overall, "signals": signals, "findings": findings, "info_alerts": info,
            "environment_alert": any("ENVIRONMENT_ALERT" in f["channels"] for f in findings),
            "team_support": any("TEAM_SUPPORT" in f["channels"] for f in findings),
            "critical_signals": [s["key"] for s in signals if s["status"] == "critical"],
            "invalid_signals": [s["key"] for s in signals if s["status"] == "invalid"],
            "disclaimer": self.rules_doc["description"],
        }

    def meta(self) -> dict:
        return {
            "version": {"thresholds": self.thresholds.get("version"), "rules": self.rules_doc.get("version")},
            "symptoms": list(self.vocab["symptoms"]),
            "symptoms_en": self.vocab["symptoms"],
            "context": list(self.vocab["context"]),
            "context_en": self.vocab["context"],
            "derived": self.derived,
            "readings": self.reading_keys(),
            "rules": [{"id": r["id"], "condition_id": r["condition_id"], "name": r["name"], "group": r["group"],
                       "levels": list(r["levels"])} for r in self.rules],
            "alert_levels": list(self.alert_levels.values()),
            "rule_groups": sorted({r["group"] for r in self.rules}),
            "treatment_library": deepcopy(self.treatment_catalog),
            "disclaimer": self.rules_doc["description"],
        }
