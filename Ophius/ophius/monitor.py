"""Continuous, profile-scoped monitoring with bounded raw retention.

Only aggregates, laboratory reports and abnormal events are durable. Ordinary
sensor samples live in a 60-second buffer. All timestamps are acquisition UTC.
"""
from __future__ import annotations

from collections import OrderedDict, deque
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import threading
import uuid

from .engine import Case, KnowledgeBase, baseline_readings, validate_profile
from .storage import Storage
from .allergies import AllergyGuard

UTC = timezone.utc
BUFFER_SECONDS = 60
ZERO_VITALS = {"heart_rate", "spo2", "blood_pressure_systolic", "blood_pressure_diastolic"}
LIVE_VITALS = ZERO_VITALS | {"skin_temperature", "qtc_interval"}
SOURCES = {"simulation", "jsonl", "tcp", "serial"}


def iso(value):
    return value.astimezone(UTC).isoformat()


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("An explicit timezone-aware ISO timestamp is required")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid ISO timestamp") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Timestamp requires an explicit timezone")
    return result.astimezone(UTC)


def number(value, label="Value", minimum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    if minimum is not None and value < minimum:
        raise ValueError(f"{label} must be at least {minimum}")
    return float(value)


def strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(text, object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"Invalid number: {value}")))


class Monitor:
    def __init__(self, data_dir, config_dir, profiles_dir, clock=None, restore_source=False):
        self.restore_source = restore_source
        self.clock = clock or (lambda: datetime.now(UTC))
        self.lock = threading.RLock()
        self.data_dir = Path(data_dir)
        self.profiles_dir = Path(profiles_dir)
        config_dir = Path(config_dir)
        self.kb = KnowledgeBase(config_dir / "thresholds.json", config_dir / "diagnostic_rules.json",
                                treatment_path=config_dir / "treatment.json")
        self.allergy_guard = AllergyGuard(config_dir/'medication_allergens.json' if (config_dir/'medication_allergens.json').exists() else None)
        self.storage = Storage(self.data_dir / "astrohealth.sqlite3")
        self.profiles = {}
        self.states = {}
        self.active_source = {}
        self.buffers = {}
        self.seen = {}
        self.last = {}
        self.pending = {}
        self.packet_ids = OrderedDict()
        self.last_timestamp = {}
        self.episodes = {}
        self.forecasts = {}
        self.closed = False
        self.inactive_streams = set()
        for profile in self.storage.load_profiles():
            self._add_loaded(profile)
        for path in sorted(self.profiles_dir.glob("*.json")):
            profile = validate_profile(strict_json(path.read_text("utf-8")))
            if profile["astronaut_id"] not in self.profiles:
                self.storage.save_profile(profile)
                self._add_loaded(profile)

    def _add_loaded(self, profile):
        aid = profile["astronaut_id"]
        self.profiles[aid] = deepcopy(profile)
        self.active_source[aid] = "observed"
        for source in ("observed", "simulation"):
            group = (aid, source)
            self.states[group] = {"symptoms": [], "context": [], "readings": {}, "reported_exposures": []}
            self.buffers[group] = deque()
            self.last[group] = {}
            self.seen[group] = {}
        # Persisted aggregate timestamps are acquisition watermarks, not raw samples.
        # A restart must not allow an old replay to inflate a daily aggregate.
        for row in self.storage.all_daily(aid):
            source, key = row.get("source"), row.get("key")
            value = row.get("last_timestamp")
            if source in {"observed", "simulation"} and key and value:
                watermark = (aid, source, key)
                acquired = timestamp(value)
                prior = self.last_timestamp.get(watermark)
                if prior is None or acquired > prior:
                    self.last_timestamp[watermark] = acquired
        # Manual reports are durable session context, not expiring sensor raws.
        for event in self.storage.events(aid):
            source = event.get("source", "observed")
            if source not in {"observed", "simulation"}:
                continue
            if event.get("kind") == "symptom_report" and isinstance(event.get("state"), dict):
                state = event["state"]
                self.states[(aid, source)] = {
                    "symptoms": [v for v in state.get("symptoms", []) if v in self.kb.vocab["symptoms"]],
                    "context": [v for v in state.get("context", []) if v in self.kb.vocab["context"]],
                    "reported_exposures": list(state.get('reported_exposures', [])),
                    "readings": {k: v for k, v in state.get("readings", {}).items()
                                 if k in self.kb.derived or (k in self.kb.signals and self.kb.signals[k].get("category") == "symptom")}}
            if event.get("packet_id"):
                self.packet_ids[(aid, source, event["packet_id"])] = True
                if event.get("key") and event.get("timestamp"):
                    watermark = (aid, source, event["key"])
                    acquired = timestamp(event["timestamp"])
                    prior = self.last_timestamp.get(watermark)
                    if prior is None or acquired > prior:
                        self.last_timestamp[watermark] = acquired
        while len(self.packet_ids) > 10000:
            self.packet_ids.popitem(last=False)

        # Testing reopens its saved partition; normal monitoring always opens observed data.
        if self.restore_source:
            selected = self.storage.selected_source(aid)
            if selected is None:
                # Older databases have no selection record. Infer the latest acquisition,
                # not a new startup session; preserve their existing anchors and history.
                candidates = [(timestamp(row['last_timestamp']), row['source'])
                    for row in self.storage.all_daily(aid) if row.get('last_timestamp')]
                candidates += [(timestamp(row['timestamp']), row['source'])
                    for row in self.storage.labs(aid)]
                candidates += [(timestamp(row['timestamp']), row['source'])
                    for row in self.storage.events(aid) if row.get('source') in {'observed','simulation'}]
                for source in ('observed','simulation'):
                    anchor = self.storage.get_anchor(aid, source)
                    if anchor:candidates.append((timestamp(anchor), source))
                selected = max(candidates, key=lambda item:(item[0], item[1]=='simulation'))[1] if candidates else 'simulation'
            self._activate_source(aid, selected)

        # Restore only findings supported by retained laboratory/context data.
        # A new, unrelated sensor sample must not announce these again.
        events = self.storage.events(aid)
        for mode in ('observed', 'simulation'):
            known = {event.get('rule_id'): event for event in events
                     if event.get('source') == mode and event.get('kind') == 'finding'}
            assessment, _ = self._assessment(aid, mode)
            for finding in assessment['findings']:
                prior = known.get(finding['rule_id'])
                if prior and prior.get('severity') == finding.get('level'):
                    self.episodes[(aid, mode, 'finding:'+finding['rule_id'])] = finding.get('level')

    def _now(self):
        value = self.clock()
        if value.tzinfo is None:
            raise ValueError("Clock must provide timezone-aware time")
        return value.astimezone(UTC)

    def _profile(self, aid):
        if aid not in self.profiles:
            raise KeyError(aid)
        return self.profiles[aid]

    def _activate_source(self, aid, mode):
        self.storage.select_source(aid, mode)
        self.active_source[aid] = mode

    def _source(self, packet_source):
        return "simulation" if packet_source == "simulation" else "observed"

    def _purge(self, group, now):
        cutoff = now - timedelta(seconds=BUFFER_SECONDS)
        buffer = self.buffers[group]
        while buffer and timestamp(buffer[0]["timestamp"]) <= cutoff:
            buffer.popleft()
        for key in list(self.last[group]):
            if timestamp(self.last[group][key]["timestamp"]) <= cutoff:
                del self.last[group][key]

    def mission_day(self, aid, source=None, at=None):
        source = source or self.active_source[aid]
        anchor = self.storage.get_anchor(aid, source)
        if not anchor:
            return None
        return max(1, ((at or self._now()).date() - timestamp(anchor).date()).days + 1)

    def _session(self, aid, source, when):
        return self.storage.session(aid, when.date().isoformat(), source)

    def _rule(self, key, aid):
        return self.kb.signal_name(key, self.profiles[aid]["personal_information"]["gender"])

    def _check_metric(self, aid, key, raw, lab=False):
        if not isinstance(raw, dict):
            raise ValueError(f"{key}: expected an object with value and unit")
        name = self._rule(key, aid)
        if name is None:
            if lab:
                return None
            raise ValueError(f"Unknown measurement: {key}")
        rule = self.kb.signals[name]
        if raw.get("unit") != rule["unit"]:
            raise ValueError(f"{key}: expected explicit unit {rule['unit']}")
        value = number(raw.get("value"), key)
        if value < 0 and key != "skin_temperature":
            raise ValueError(f"{key}: negative values are invalid")
        if key in {"spo2", "hematocrit", "reticulocytes"} and value > 100:
            raise ValueError(f"{key}: percentage must not exceed 100")
        metadata = raw.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ValueError(f"{key}: metadata must be an object")
        metadata = deepcopy(metadata)
        for field in ("coverage_start", "coverage_end"):
            if field in metadata:
                timestamp(metadata[field])
        if "coverage_start" in metadata and "coverage_end" in metadata:
            if timestamp(metadata["coverage_end"]) <= timestamp(metadata["coverage_start"]):
                raise ValueError("Exposure coverage end must follow start")
        if rule["category"] == "radiation" and metadata.get("kind", "reported_window") not in {"interval", "cumulative", "reported_window"}:
            raise ValueError("Radiation kind must be interval, cumulative or reported_window")
        for flag in ("verified", "career_complete", "baseline_verified"):
            if flag in metadata and not isinstance(metadata[flag], bool):
                raise ValueError(f"{flag} must be a boolean")
        return {"value": value, "unit": raw["unit"], "metadata": metadata, "rule_name": name}

    def ingest(self, aid, packet):
        with self.lock:
            self._profile(aid)
            if not isinstance(packet, dict):
                raise ValueError("Sensor packet must be an object")
            source = packet.get("source", "jsonl")
            if source not in SOURCES:
                raise ValueError("Unsupported packet source")
            mode = self._source(source)
            group = (aid, mode)
            when = timestamp(packet.get("timestamp"))
            now = self._now()
            if when > now + timedelta(seconds=5):
                raise ValueError("Future acquisition timestamps are rejected")
            quality = packet.get("quality", "ok")
            if quality not in {"ok", "invalid", "disconnected"}:
                raise ValueError("Unsupported packet quality")
            data = packet.get("readings")
            if not isinstance(data, dict) or not data:
                raise ValueError("Packet must supply a nonempty readings object")
            clean = {key: self._check_metric(aid, key, value) for key, value in data.items()}
            packet_id = packet.get("packet_id") or hashlib.sha256(json.dumps(packet, sort_keys=True, allow_nan=False).encode()).hexdigest()
            if not isinstance(packet_id, str) or not packet_id or len(packet_id) > 160:
                raise ValueError("packet_id must be a nonempty string, at most 160 characters")
            dedup = (aid, mode, packet_id)
            if dedup in self.packet_ids:
                raise ValueError("Duplicate packet")
            # Reject whole packets that would replace newer values for any supplied metric.
            for key in clean:
                last_time = self.last_timestamp.get((aid, mode, key))
                if last_time is not None and when <= last_time:
                    raise ValueError(f"{key}: acquisition timestamp must advance")
            # All validation finishes before state mutations.
            self._flush_before(when.date())
            self._purge(group, now)
            self._activate_source(aid, mode)
            session_id = self._session(aid, mode, when)
            if quality == "ok":
                self.storage.anchor(aid, iso(when), mode)
            self.packet_ids[dedup] = True
            while len(self.packet_ids) > 10000:
                self.packet_ids.popitem(last=False)
            for key, item in clean.items():
                observation = {**item, "timestamp": iso(when), "source": source,
                               "quality": quality, "packet_id": packet_id}
                previous = self.last[group].get(key)
                self.last_timestamp[(aid, mode, key)] = when
                self.seen[group][key] = {"timestamp": iso(when), "source": source, "quality": quality,
                                         "unit": item["unit"]}
                self.last[group][key] = observation
                self.buffers[group].append({"key": key, **observation})
                if quality == "ok":
                    self._aggregate(aid, mode, session_id, when, key, observation, previous)
                    stale_episode = (aid, mode, "stale:" + key)
                    if stale_episode in self.episodes:
                        del self.episodes[stale_episode]
                        self.storage.add_event(aid, session_id, "recovery", {"timestamp": iso(when), "source": mode,
                            "key": key, "severity": "INFO", "message": f"{key}: sensor samples resumed"})
                status, reason = self._status(aid, key, observation)
                if quality != "ok":
                    self._event_episode(aid, mode, session_id, "sensor:" + key, when,
                        {"kind": "sensor_fault", "key": key, "severity": "TECHNICAL", "message": f"{key}: {quality}; check sensor contact", "quality": quality, "value": item["value"], "unit": item["unit"], "packet_id": packet_id, "transport": source})
                elif key in ZERO_VITALS and item["value"] == 0:
                    elevated = any(r["key"] == "heart_rate" and r["quality"] == "ok" and
                                   r["value"] > self.kb.signals["heart_rate"].get("caution_above", 100)
                                   for r in self.buffers[group]) if key == "heart_rate" else False
                    payload = {"kind": "possible_cardiac_arrest" if key == "heart_rate" else "zero_vital",
                        "key": key, "value": 0, "unit": item["unit"], "severity": "EMERGENCY",
                        "message": "Possible cardiac arrest — verify pulse, responsiveness and sensor contact immediately" if key == "heart_rate" else f"Zero {key} — check immediately",
                        "sequence_within_buffer": elevated, "packet_id": packet_id, "transport": source,
                        "preceding_values": [{"timestamp": r["timestamp"], "value": r["value"]} for r in self.buffers[group] if r["key"] == key],
                        "treatments": self.kb.treatment_for("sudden_cardiac_arrest") if key == "heart_rate" else []}
                    self._event_episode(aid, mode, session_id, "zero:" + key, when, payload)
                elif status in {"caution", "critical"}:
                    self._event_episode(aid, mode, session_id, "limit:" + key, when,
                        {"kind": "threshold", "key": key, "value": item["value"], "unit": item["unit"],
                         "severity": "URGENT" if status == "critical" else "MONITOR", "status": status,
                         "message": f"{key}: {item['value']:g} {item['unit']} — {status}", "reason": reason, "packet_id": packet_id, "transport": source})
                else:
                    self._recover(aid, mode, session_id, key, when)
            self._update_finding_events(aid, mode, session_id, when)
            return self.snapshot(aid)

    def _aggregate(self, aid, mode, sid, when, key, item, previous):
        stat_day = when.date()
        md = item.get("metadata", {})
        if md.get("kind") == "interval" and md.get("verified") is True and md.get("coverage_start") and md.get("coverage_end"):
            begin, finish = timestamp(md["coverage_start"]), timestamp(md["coverage_end"])
            # A complete UTC-day interval reported at the following midnight
            # belongs to the exposure day. Never apportion an interval by guessing.
            if begin.date() == (finish - timedelta(microseconds=1)).date() and finish <= when:
                stat_day = begin.date()
                sid = self._session(aid, mode, begin)
        pk = (sid, key, item['unit'])
        if pk not in self.pending:
            prior = next((row for row in self.storage.all_daily(aid) if row["session_id"] == sid and row["key"] == key and row['unit'] == item['unit']), None)
            if prior:
                self.pending[pk] = prior
        stat = self.pending.setdefault(pk, {"session_id": sid, "aid": aid, "source": mode,
            "day": stat_day.isoformat(), "key": key, "unit": item["unit"], "count": 0,
            "sum": 0.0, "minimum": item["value"], "maximum": item["value"],
            "weighted_sum": 0.0, "coverage_seconds": 0.0,
            "first_timestamp": item["timestamp"], "last_timestamp": item["timestamp"],
            "abnormal_count": 0, "dose_total": None, "dose_coverage_seconds": 0.0})
        stat["count"] += 1
        stat["sum"] += item["value"]
        stat["minimum"] = min(stat["minimum"], item["value"])
        stat["maximum"] = max(stat["maximum"], item["value"])
        stat["last_timestamp"] = item["timestamp"]
        status, _ = self._status(aid, key, item)
        stat["abnormal_count"] += status in {"caution", "critical"} or (key in ZERO_VITALS and item["value"] == 0)
        if previous and previous["quality"] == "ok" and previous['unit'] == item['unit']:
            duration = (when - timestamp(previous["timestamp"])).total_seconds()
            # Never extrapolate through a disconnection or an unobserved interval.
            midnight = datetime.combine(when.date(), datetime.min.time(), UTC)
            duration = min(duration, (when - midnight).total_seconds())
            if 0 < duration <= BUFFER_SECONDS:
                stat["weighted_sum"] += previous["value"] * duration
                stat["coverage_seconds"] += duration
        rule = self.kb.signals[item["rule_name"]]
        if rule["category"] == "radiation":
            md = item["metadata"]
            if mode == 'simulation' and md.get('synthetic_scenario_id') and md.get('synthetic_scenario_id') != stat.get('reported_metadata',{}).get('synthetic_scenario_id'):
                # Independent hypothetical fixtures are not a continuous dose counter.
                stat.pop('dose_context_error',None)
            kind = md.get("kind", "reported_window")
            if kind == "interval":
                start, end = md.get("coverage_start"), md.get("coverage_end")
                if md.get("verified") is True and start and end:
                    begin, finish = timestamp(start), timestamp(end)
                    if finish <= when and begin.date() == (finish - timedelta(microseconds=1)).date():
                        last_end = stat.get("dose_coverage_end")
                        if last_end and begin < timestamp(last_end):
                            stat["dose_context_error"] = "Overlapping intervals cannot be accumulated"
                        else:
                            if last_end and begin != timestamp(last_end):
                                stat["dose_has_gaps"] = True
                            stat["dose_total"] = (stat["dose_total"] or 0) + item["value"]
                            stat["dose_coverage_seconds"] += (finish - begin).total_seconds()
                            stat.setdefault("dose_coverage_start", start)
                            stat["dose_coverage_end"] = end
                            stat["dose_kind"] = "interval"
                            stat["dose_verified"] = True
            elif kind in {"cumulative", "reported_window"}:
                # Retain the declared aggregate, not a sum of cumulative snapshots.
                previous_counter = stat.get("reported_total")
                if previous_counter is None and kind == "cumulative":
                    old = [row for row in self.storage.all_daily(aid)
                           if row["key"] == key and row["source"] == mode
                           and row.get("reported_total") is not None]
                    if old:
                        previous_counter = max(old, key=lambda row: row["last_timestamp"])["reported_total"]
                if kind == "cumulative" and previous_counter is not None and item["value"] < previous_counter:
                    stat["dose_context_error"] = "Counter reset: establish a new verified baseline"
                stat["reported_total"] = item["value"]
                stat["reported_metadata"] = deepcopy(md)
                stat["dose_kind"] = kind
                if kind == "cumulative" and previous and item["value"] < previous["value"]:
                    stat["dose_context_error"] = "Counter reset: establish a new verified baseline"

    def _status(self, aid, key, observation):
        if observation.get("quality") != "ok":
            return "invalid", "Sensor quality is " + observation.get("quality", "invalid")
        if observation.get("context_error"):
            return "needs_context", observation["context_error"]
        rule = self.kb.signals[observation["rule_name"]]
        if observation.get('unit') != rule['unit']:
            return 'needs_context', f"Saved unit {observation.get('unit')} differs from current reference {rule['unit']}; import a correctly unit-labelled result"
        value = observation["value"]
        window = rule.get("window", "instant")
        md = observation.get("metadata", {})
        acquisition = timestamp(observation["timestamp"])
        if md.get("coverage_end") and timestamp(md["coverage_end"]) > acquisition:
            return "needs_context", "Coverage extends beyond acquisition"
        if rule["category"] == "radiation":
            mode = self._source(observation.get("source", "jsonl"))
            known_rows = [row for row in self.storage.all_daily(aid) if row["source"] == mode and row["key"] == key]
            known_rows.extend(row for row in self.pending.values() if row["aid"] == aid and row["source"] == mode and row["key"] == key)
            if mode=='simulation' and md.get('synthetic_scenario_id'):
                known_rows=[row for row in known_rows if row.get('reported_metadata',{}).get('synthetic_scenario_id')==md['synthetic_scenario_id']]
            if any(row.get("dose_context_error") for row in known_rows):
                return "needs_context", "Exposure counter reset or overlapping intervals require a new verified baseline"
            md = observation.get("metadata", {})
            if md.get("verified") is not True:
                return "needs_context", "Verified exposure coverage is required"
            start, end = md.get("coverage_start"), md.get("coverage_end")
            if not start or not end:
                return "needs_context", "Exposure start and end are required"
            begin, finish = timestamp(start), timestamp(end)
            if finish > timestamp(observation["timestamp"]):
                return "needs_context", "Exposure coverage extends beyond acquisition"
            if md.get("kind", "reported_window") == "interval":
                return "needs_context", "Interval increment is accumulated; it is not a complete reporting window"
            if md.get("window") != window:
                return "needs_context", "Declared exposure window does not match threshold"
            duration = (finish - begin).total_seconds()
            if window == "30_days" and abs(duration - 30 * 86400) > 1:
                return "needs_context", "Thirty full days of exposure coverage are required"
            if window == "1_year" and duration < 365 * 86400:
                return "needs_context", "A full year of exposure coverage is required"
            if window == "career" and md.get("career_complete") is not True:
                return "needs_context", "Complete career dosimetry must be declared"
            if window == "per_mission_year":
                anchor = self.storage.get_anchor(aid, mode)
                if anchor is None or begin > timestamp(anchor):
                    return "needs_context", "Dose report must cover the complete mission-to-date period"
                if abs((acquisition - finish).total_seconds()) > 1:
                    return "needs_context", "Mission dose coverage must extend through acquisition"
        elif window == "1_hour_average":
            md = observation.get("metadata", {})
            if md.get("verified") is not True or md.get("window") != "1_hour_average":
                return "needs_context", "A verified one-hour partial-pressure average is required"
            if "coverage_start" in md and "coverage_end" in md:
                duration = (timestamp(md["coverage_end"]) - timestamp(md["coverage_start"])).total_seconds()
                if abs(duration - 3600) > 1:
                    return "needs_context", "CO2 reporting interval must be one hour"
        case = Case(sex=self.profiles[aid]["personal_information"]["gender"],
                    mission_duration_days=self.profiles[aid]["mission_details"]["duration_days"])
        limits = self.kb.limits_for(observation["rule_name"], case)
        return self.kb.classify(observation["rule_name"], value, limits), "Compared with the supplied threshold"

    def _event_episode(self, aid, mode, sid, episode, when, payload):
        key = (aid, mode, episode)
        signature = payload.get("severity")
        if self.episodes.get(key) == signature:
            return
        self.episodes[key] = signature
        event = {**payload, "timestamp": iso(when), "source": mode, "synthetic": mode == "simulation"}
        if 'treatments' in event:
            event['treatments'] = [self.allergy_guard.treatment(self.profiles[aid],item) for item in event['treatments']]
        self.storage.add_event(aid, sid, event["kind"], event)

    def _recover(self, aid, mode, sid, key, when):
        for prefix in ("limit:", "zero:", "sensor:", "lab:"):
            episode = (aid, mode, prefix + key)
            if episode in self.episodes:
                del self.episodes[episode]
                self.storage.add_event(aid, sid, "recovery", {"timestamp": iso(when), "source": mode,
                    "key": key, "severity": "INFO", "message": f"{key}: new valid reading no longer triggers this alert"})

    def _update_finding_events(self, aid, mode, sid, when):
        assessment, _ = self._assessment(aid, mode)
        active = set()
        for finding in assessment.get("findings", []):
            fid = finding["rule_id"]
            active.add("finding:" + fid)
            self._event_episode(aid, mode, sid, "finding:" + fid, when,
                {"kind": "finding", "severity": finding.get("level", "MONITOR"),
                 "message": finding["name"], "rule_id": fid, "finding": finding})
        for key in list(self.episodes):
            if key[:2] == (aid, mode) and key[2].startswith("finding:") and key[2] not in active:
                del self.episodes[key]

    def _lab_values(self, aid, mode):
        latest = {}
        for report in self.storage.labs(aid):
            if report.get("source") != mode:
                continue
            for key, item in report.get("readings", {}).items():
                if key not in latest or timestamp(item["timestamp"]) > timestamp(latest[key]["timestamp"]):
                    latest[key] = item
        return latest

    def _retained_doses(self, aid, mode):
        result = {}
        for key, rule in self.kb.signals.items():
            if rule.get("category") != "radiation":
                continue
            total, reason, rows = self._known_total(aid, mode, key)
            if not rows:
                continue
            latest = max(rows, key=lambda row: row["last_timestamp"])
            metadata = deepcopy(latest.get("reported_metadata", {}))
            if total is None:
                totals = [row["dose_total"] for row in rows if row.get("dose_total") is not None]
                if totals:
                    value = sum(totals)
                    metadata = {"kind": "interval"}
                elif latest.get("reported_total") is not None:
                    value = latest["reported_total"]
                else:
                    continue
            else:
                value = total
                if not metadata:
                    metadata = {"kind": "reported_window", "verified": True,
                        "window": rule.get("window"),
                        "coverage_start": rows[0].get("dose_coverage_start"),
                        "coverage_end": latest.get("dose_coverage_end")}
            result[key] = {"value": value, "unit": rule["unit"], "rule_name": key,
                "metadata": metadata, "timestamp": latest["last_timestamp"],
                "source": mode, "quality": "ok", "retained_aggregate": True,
                "aggregate_note": reason, "context_error": reason if total is None else None}
        return result

    def _assessment(self, aid, mode):
        group = (aid, mode)
        self._purge(group, self._now())
        eligible = {}
        observations = dict(self.last[group])
        observations.update(self._retained_doses(aid, mode))
        observations.update(self._lab_values(aid, mode))
        for key, item in observations.items():
            status, _ = self._status(aid, key, item)
            if status in {"normal", "caution", "critical"}:
                eligible[key] = item["value"]
        st = self.states[group]
        eligible.update(st["readings"])
        matched_exposures = self.allergy_guard.exposure_matches(self.profiles[aid], st.get('reported_exposures', []))
        context = set(st['context'])
        if matched_exposures:
            context.add('suspected_allergen_exposure')
        day = self.mission_day(aid, mode)
        if day is not None:
            eligible["mission_day"] = day
        assessment = self.kb.assess(Case(sex=self.profiles[aid]["personal_information"]["gender"],
            symptoms=set(st["symptoms"]), context=context, readings=eligible,
            mission_duration_days=self.profiles[aid]["mission_details"]["duration_days"]))
        # No live/lab evidence must never become a reassuring NORMAL banner.
        meaningful = {k: v for k, v in eligible.items() if k != "mission_day"}
        if not meaningful and not assessment.get("findings"):
            assessment["overall"] = "UNKNOWN"
        if any(key in ZERO_VITALS and value == 0 for key, value in meaningful.items()):
            assessment["overall"] = "EMERGENCY"
        if meaningful.get("heart_rate") == 0:
            elevated = any(r["key"] == "heart_rate" and r["quality"] == "ok" and
                r["value"] > self.kb.signals["heart_rate"].get("caution_above", 100)
                for r in self.buffers[group])
            assessment["findings"].insert(0, {
                "rule_id": "HEART_RATE_ZERO", "condition_id": "sudden_cardiac_arrest",
                "name": "Possible cardiac arrest — verify immediately", "group": "Emergency warning",
                "level": "EMERGENCY", "numeric_level": "EMERGENCY", "channels": [],
                "evidence": [{"kind": "signal", "key": "heart_rate", "value": 0, "unit": "bpm"}],
                "sequence_within_buffer": elevated,
                "logic": "A quality-valid device-reported zero heart rate triggers an immediate possible-arrest warning. " +
                         ("An elevated heart rate preceded zero within the 60-second buffer." if elevated else "No preceding elevated rate is required to warn."),
                "confirmation": ["Check responsiveness and breathing immediately.", "Verify pulse and sensor contact; a numeric zero alone does not confirm cardiac arrest."],
                "treatments": self.kb.treatment_for("sudden_cardiac_arrest"),
                "hide_therapy": False, "red_flag": True,
                "red_flag_text": "Possible emergency; distinguish a genuine loss of pulse from sensor failure.",
                "limitations": "The sequence is a theoretical warning trigger, not an independently confirmed diagnosis.",
                "do_not": [], "severity_markers": [], "privacy_sensitive": False,
                "source": {"reference": "User-specified simulated emergency trigger"}})
        assessment['allergy_context'] = {'recorded_allergies': self.allergy_guard.allergies(self.profiles[aid])[0],
            'reported_exposures': list(st.get('reported_exposures', [])), 'matched_exposures': matched_exposures}
        assessment['findings'] = [self.allergy_guard.finding(self.profiles[aid], f) for f in assessment['findings']]
        for finding in assessment['findings']:
            if finding.get('rule_id') in {'C01', 'C02'}:
                finding['allergy_evidence'] = matched_exposures
        return assessment, observations

    def snapshot(self, aid):
        with self.lock:
            profile = self._profile(aid)
            mode = self.active_source[aid]
            group = (aid, mode)
            assessment, observations = self._assessment(aid, mode)
            baselines = baseline_readings(profile)
            rows = []
            labs = self._lab_values(aid, mode)
            for spec in self.kb.reading_keys():
                key = spec["key"]
                item = observations.get(key)
                baseline = baselines.get(key)
                if item:
                    status, reason = self._status(aid, key, item)
                    row = {"key": key, "label": spec["label"], "unit": item["unit"], "value": item["value"],
                        "timestamp": item["timestamp"], "source": item["source"], "status": status,
                        "reason": reason, "type": "lab" if key in labs else "accumulated" if item.get("retained_aggregate") else "sensor", "baseline": baseline}
                else:
                    seen = self.seen[group].get(key)
                    row = {"key": key, "label": spec["label"], "unit": spec["unit"], "value": None,
                        "timestamp": seen["timestamp"] if seen else None, "source": seen["source"] if seen else None,
                        "status": "stale" if seen else "missing", "reason": "No sample in the last 60 seconds" if seen else "No measurement supplied",
                        "type": "sensor", "baseline": baseline}
                rows.append(row)
            events = self.storage.events(aid)
            alerts = [event for event in events if not event.get("acknowledged") and event.get('severity') != 'INFO' and event.get("kind") not in {"recovery", "symptom_report"} and event.get("source") == mode]
            for event in alerts:
                if 'treatments' in event:
                    event['treatments'] = [self.allergy_guard.treatment(profile,item) for item in event['treatments']]
                if 'finding' in event:
                    event['finding'] = self.allergy_guard.finding(profile,event['finding'])
            sid = self._session(aid, mode, self._now()) if self.storage.get_anchor(aid, mode) else None
            return {"id": aid, "profile": deepcopy(profile), "mission_day": self.mission_day(aid, mode),
                "session_id": sid, "active_source": mode, "readings": rows, "assessment": assessment,
                "alerts": alerts, "state": deepcopy(self.states[group]),
                "forecasts": self._auto_forecasts(aid, mode),
                "monitoring": {"buffer_seconds": BUFFER_SECONDS, "buffer_samples": len(self.buffers[group]),
                    "source": mode, "synthetic": mode == "simulation", "raw_storage": "memory_only",
                    "retention_note": "Daily/session aggregates and abnormal events persist; normal raw samples expire after 60 seconds",
                    "lab_note": "Imported laboratory values retain their report dates; clinical freshness is not inferred"}}

    def list_profiles(self):
        with self.lock:
            rows = []
            for aid, profile in self.profiles.items():
                snap = self.snapshot(aid)
                rows.append({"id": aid, "gender": profile["personal_information"]["gender"],
                    "mission_day": snap["mission_day"], "mission_duration_days": profile["mission_details"]["duration_days"],
                    "overall": snap["assessment"]["overall"], "active_alerts": len(snap["alerts"]),
                    "active_source": snap["active_source"], "mission_name": profile["mission_details"].get("mission_name", "")})
            return rows

    def add_profile(self, raw):
        with self.lock:
            profile = validate_profile(raw)
            aid = profile["astronaut_id"]
            if aid in self.profiles:
                raise ValueError("An astronaut with this ID already exists")
            self.storage.save_profile(profile)
            self._add_loaded(profile)
            return next(row for row in self.list_profiles() if row["id"] == aid)

    def import_lab(self, aid, report):
        with self.lock:
            self._profile(aid)
            if not isinstance(report, dict):
                raise ValueError("Laboratory report must be an object")
            when = timestamp(report.get("timestamp", report.get("date")))
            if when > self._now() + timedelta(seconds=5):
                raise ValueError("Future laboratory report is not accepted")
            if "synthetic" in report and not isinstance(report["synthetic"], bool):
                raise ValueError("synthetic must be boolean")
            mode = "simulation" if report.get("synthetic", False) else "observed"
            data = report.get("readings", report.get("measurements", report.get("results")))
            if not isinstance(data, dict) or not data:
                raise ValueError("Laboratory report needs readings with explicit values and units")
            clean, ignored = {}, []
            for key, raw in data.items():
                metric = self._check_metric(aid, key, raw, lab=True)
                if metric is None:
                    ignored.append(key)
                    continue
                if self.kb.signals[metric["rule_name"]]["category"] != "blood_panel":
                    raise ValueError(f"{key}: laboratory import accepts blood-panel measurements only")
                clean[key] = {**metric, "timestamp": iso(when), "source": "simulation" if mode == "simulation" else "manual_lab", "quality": "ok"}
            if not clean:
                raise ValueError("No threshold-supported laboratory measurements in this report")
            rid = report.get("report_id") or hashlib.sha256(json.dumps(report, sort_keys=True, allow_nan=False).encode()).hexdigest()
            if not isinstance(rid, str) or not rid or len(rid) > 160:
                raise ValueError("Invalid report_id")
            if self.storage.has_lab(aid, rid):
                raise ValueError("Duplicate laboratory report")
            saved = {"report_id": rid, "timestamp": iso(when), "synthetic": mode == "simulation",
                "readings": clean, "ignored_measurements": ignored,
                "note": "No supplied thresholds; not assessed: " + ", ".join(ignored) if ignored else ""}
            self.storage.save_lab(aid, mode, saved)
            self._activate_source(aid, mode)
            self.storage.anchor(aid, iso(when), mode)
            sid = self._session(aid, mode, when)
            for key, item in clean.items():
                self._aggregate(aid, mode, sid, when, key, item, None)
                status, reason = self._status(aid, key, item)
                if status in {"caution", "critical"}:
                    self._event_episode(aid, mode, sid, "lab:" + key, when,
                        {"kind": "laboratory", "key": key, "value": item["value"], "unit": item["unit"],
                         "severity": "MONITOR" if status == "caution" else "URGENT", "message": f"{key}: {status}", "report_id": rid})
                else:
                    self._recover(aid, mode, sid, key, when)
            self._update_finding_events(aid, mode, sid, when)
            snap = self.snapshot(aid)
            snap["import"] = {"report_id": rid, "ignored_measurements": ignored, "note": saved["note"]}
            return snap

    def update_symptoms(self, aid, payload):
        with self.lock:
            self._profile(aid)
            if not isinstance(payload, dict):
                raise ValueError("Symptoms payload must be an object")
            mode = self.active_source[aid]
            st = deepcopy(self.states[(aid, mode)])
            for field in ("symptoms", "context"):
                if field in payload:
                    value = payload[field]
                    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
                        raise ValueError(f"{field} must be a list of identifiers")
                    unknown = set(value) - set(self.kb.vocab[field])
                    if unknown:
                        raise ValueError(f"Unknown {field}: {', '.join(sorted(unknown))}")
                    st[field] = sorted(set(value))
            if 'reported_exposures' in payload:
                exposures = payload['reported_exposures']
                if not isinstance(exposures, list) or len(exposures) > 50 or any(not isinstance(v, str) or not v.strip() or len(v) > 160 for v in exposures):
                    raise ValueError('Reported exposures must be a list of up to 50 nonempty names')
                if any(v.strip().lower().startswith(('no ', 'not ', 'never ', 'denies ')) for v in exposures):
                    raise ValueError('Enter names of actual exposures; leave the list empty instead of entering a negated statement')
                st['reported_exposures'] = list(dict.fromkeys(v.strip() for v in exposures))
            values = payload.get("readings", {})
            if not isinstance(values, dict):
                raise ValueError("Derived readings must be an object")
            for key, value in values.items():
                manual_rule = self._rule(key, aid)
                if key not in self.kb.derived and not (manual_rule and self.kb.signals[manual_rule].get("category") == "symptom"):
                    raise ValueError(f"Unknown derived/manual measurement: {key}")
                if value is None:
                    st["readings"].pop(key, None)
                else:
                    st["readings"][key] = number(value, key, minimum=0)
            self.states[(aid, mode)] = st
            when = self._now()
            sid = self._session(aid, mode, when)
            self.storage.add_event(aid, sid, "symptom_report", {"timestamp": iso(when), "source": mode,
                "severity": "INFO", "message": "Manual symptom/context report", "state": deepcopy(st), "acknowledged": True})
            self._update_finding_events(aid, mode, sid, when)
            return self.snapshot(aid)

    def acknowledge(self, aid, event_id):
        with self.lock:
            self._profile(aid)
            if not self.storage.acknowledge(aid, event_id):
                raise KeyError(event_id)
            return self.snapshot(aid)

    def check_medication(self, aid, payload):
        with self.lock:
            profile = self._profile(aid)
            if not isinstance(payload, dict):
                raise ValueError('Medication check must be an object')
            return self.allergy_guard.check(profile, payload.get('medication'))

    def record_medication(self, aid, payload):
        with self.lock:
            check = self.check_medication(aid, payload)
            if not check['recording_allowed']:
                raise ValueError('Medication entry blocked: '+check['reason'])
            note = payload.get('note', '')
            if not isinstance(note, str) or len(note) > 2000:
                raise ValueError('Medication note must be text up to 2000 characters')
            mode, now = self.active_source[aid], self._now()
            event = self.storage.add_event(aid, self._session(aid, mode, now), 'medication_record', {
                'timestamp': iso(now), 'source': mode, 'severity': 'INFO', 'medication': check['ingredient'],
                'message': 'Manual medication record: '+check['ingredient'], 'note': note, 'allergy_check': check})
            self.storage.acknowledge(aid, event['id'])
            return event

    def update_allergies(self, aid, payload):
        with self.lock:
            profile = deepcopy(self._profile(aid))
            values = payload.get('allergies') if isinstance(payload, dict) else None
            if not isinstance(values, list) or len(values) > 50 or any(not isinstance(x, str) or not x.strip() or len(x) > 160 for x in values):
                raise ValueError('Allergies must be a list of up to 50 names; use unknown if history is not established')
            values = list(dict.fromkeys(v.strip() for v in values))
            if any(v.lower() in {'none', 'no known allergies', 'nkda'} for v in values) and len(values) > 1:
                raise ValueError('Do not combine none with named allergies')
            profile.setdefault('medical_history', {})['allergies'] = values
            self.storage.save_profile(profile)
            self.profiles[aid] = profile
            now, mode = self._now(), self.active_source[aid]
            self.storage.add_event(aid, self._session(aid, mode, now), 'profile_update', {
                'timestamp':iso(now), 'source':mode, 'severity':'INFO', 'message':'Allergy history updated', 'allergies':values})
            self._update_finding_events(aid, mode, self._session(aid, mode, now), now)
            return self.snapshot(aid)

    def _stat_export(self, stat):
        value = deepcopy(stat)
        value["mean"] = value["sum"] / value["count"] if value["count"] else None
        value["time_weighted_mean"] = value["weighted_sum"] / value["coverage_seconds"] if value["coverage_seconds"] else None
        value["coverage_fraction_of_day"] = value["coverage_seconds"] / 86400
        return value

    def _flush_before(self, day):
        for key, stat in list(self.pending.items()):
            if date.fromisoformat(stat["day"]) < day:
                self.storage.save_daily(stat["session_id"], stat["key"], stat["unit"], self._stat_export(stat))
                del self.pending[key]

    def tick(self):
        with self.lock:
            now = self._now()
            for group in self.buffers:
                self._purge(group, now)
                aid, mode = group
                if group in self.inactive_streams:
                    continue
                for key, seen in self.seen[group].items():
                    if key not in LIVE_VITALS or seen.get("quality") != "ok":
                        continue
                    if (now - timestamp(seen["timestamp"])).total_seconds() >= BUFFER_SECONDS:
                        sid = self._session(aid, mode, now)
                        self._event_episode(aid, mode, sid, "stale:" + key, now,
                            {"kind": "sensor_stale", "key": key, "severity": "TECHNICAL",
                             "message": f"{key}: no samples in 60 seconds; monitoring source may have stopped",
                             "last_acquisition": seen["timestamp"], "transport": seen["source"]})
            self._flush_before(now.date())

    def set_stream_active(self, aid, source, active):
        with self.lock:
            self._profile(aid)
            group=(aid,source)
            if active:self.inactive_streams.discard(group)
            else:self.inactive_streams.add(group)

    def history(self, aid):
        with self.lock:
            self._profile(aid)
            result = self.storage.history(aid)
            # Present in-progress aggregate separately; it is not a raw sample log.
            result["daily"] = [row for row in result["daily"] if (row["session_id"], row["key"], row['unit']) not in self.pending]
            result["daily"].extend(self._stat_export(row) for row in self.pending.values() if row["aid"] == aid)
            result["retention"] = {"raw_seconds": 60, "normal_raw_persisted": False,
                "daily_write_policy": "UTC day rollover and clean shutdown; current-day aggregates can be lost on abrupt termination",
                "abnormal_write_policy": "Immediate", "lab_write_policy": "Immediate"}
            return result

    def _dose_rows(self, aid, mode, key):
        rows = [row for row in self.history(aid)["daily"] if row["source"] == mode and row["key"] == key]
        if mode=='simulation' and rows:
            latest=max(rows,key=lambda row:row['last_timestamp'])
            scenario=latest.get('reported_metadata',{}).get('synthetic_scenario_id')
            if scenario:rows=[row for row in rows if row.get('reported_metadata',{}).get('synthetic_scenario_id')==scenario]
        return sorted(rows, key=lambda row: row["day"])

    def _known_total(self, aid, mode, key):
        rows = self._dose_rows(aid, mode, key)
        if not rows:
            return None, "No retained exposure aggregate", rows
        if any(row['unit'] != self.kb.signals[key]['unit'] for row in rows):
            return None, 'Exposure history units differ from the current reference', rows
        if any(row.get("dose_context_error") for row in rows):
            return None, "Exposure history contains a counter reset or overlap", rows
        reports = [row for row in rows if row.get("reported_total") is not None]
        if reports:
            latest = max(reports, key=lambda row: row["last_timestamp"])
            observation = {"value": latest["reported_total"], "unit": latest["unit"], "quality": "ok",
                "timestamp": latest["last_timestamp"], "metadata": latest.get("reported_metadata", {}), "rule_name": key, "source": mode}
            status, reason = self._status(aid, key, observation)
            if status in {"normal", "caution", "critical"}:
                return latest["reported_total"], "Verified reported exposure total", rows
            return None, reason, rows
        intervals = [row for row in rows if row.get("dose_total") is not None and row.get("dose_verified")]
        if not intervals:
            return None, "Verified exposure intervals are unavailable", rows
        if len(intervals) != len(rows) or any(row.get("dose_has_gaps") for row in intervals):
            return None, "Incomplete interval exposure coverage", rows
        for earlier, later in zip(intervals, intervals[1:]):
            if timestamp(earlier["dose_coverage_end"]) != timestamp(later["dose_coverage_start"]):
                return None, "Exposure acquisition has gaps", rows
        rule = self.kb.signals[key]
        window = rule.get("window")
        if window == "career":
            return None, "Career baseline completeness is not verified", rows
        start = timestamp(intervals[0]["dose_coverage_start"])
        end = timestamp(intervals[-1]["dose_coverage_end"])
        if window in {"30_days", "1_year"}:
            required = 30 if window == "30_days" else 365
            if abs((end - start).total_seconds() - required * 86400) > 1:
                return None, f"Complete {required}-day exposure window is unavailable", rows
        if window == "per_mission_year":
            anchor = self.storage.get_anchor(aid, mode)
            if anchor and start > timestamp(anchor):
                return None, "Mission exposure before the first dose interval is unknown", rows
        return sum(row["dose_total"] for row in intervals), "Verified contiguous interval totals", rows

    def _auto_forecasts(self, aid, mode):
        output = []
        for key, rule in self.kb.signals.items():
            if rule.get("category") != "radiation":
                continue
            total, reason, rows = self._known_total(aid, mode, key)
            base = {"key": key, "status": "insufficient_data", "kind": "projection", "unit": rule["unit"]}
            if total is None:
                output.append({**base, "reason": reason})
                continue
            if rule.get("window") in {"30_days", "1_year"}:
                output.append({**base, "reason": "Rolling-window prediction requires age-resolved exposure; a fixed window total is insufficient"})
                continue
            points = []
            for row in rows:
                md = row.get("reported_metadata", {})
                if row.get("dose_kind") == "cumulative" and md.get("verified") is True:
                    points.append((timestamp(row["last_timestamp"]), row.get("reported_total")))
            if len({p[0].date() for p in points}) >= 3:
                points.sort()
                first, last = points[0][0], points[-1][0]
                if any(b[1] < a[1] for a, b in zip(points, points[1:])):
                    output.append({**base, "reason": "Cumulative counter reset prevents a trend estimate"})
                    continue
                days = (last - first).total_seconds() / 86400
                rate = (points[-1][1] - points[0][1]) / days if days > 0 else 0
                basis_note = "Difference between verified cumulative reports; intervening variation is unknown"
            else:
                usable = [row for row in rows if row.get("dose_total") is not None and row.get("dose_verified")]
                if len({row["day"] for row in usable}) < 3:
                    output.append({**base, "reason": "At least three distinct measured dates are required"})
                    continue
                last = timestamp(usable[-1]["dose_coverage_end"])
                first = timestamp(usable[0]["dose_coverage_start"])
                days = (last - first).total_seconds() / 86400
                rate = sum(row["dose_total"] for row in usable) / days if days > 0 else 0
                basis_note = "Contiguous verified dose intervals"
            if days < 2:
                output.append({**base, "reason": "At least two full elapsed days spanning three measured dates are required"})
                continue
            if self._now() - last > timedelta(hours=24):
                output.append({**base, "reason": "Latest exposure is older than 24 hours"})
                continue
            result = self._projection(aid, key, total, rate, 21, "measured_trend", last)
            result["data_basis"] = basis_note
            result["observed_span_days"] = days
            output.append(result)
        return output

    def _projection(self, aid, key, current, rate, horizon, basis, at=None):
        rule = self.kb.signals[key]
        limit = rule.get("critical_above", rule.get("caution_above"))
        if rule.get("scales_with_mission_duration"):
            limit *= self.profiles[aid]["mission_details"]["duration_days"] / 365.0
        if limit is None:
            raise ValueError("No high exposure threshold is configured")
        days = max(0.0, (limit - current) / rate) if rate > 0 else None
        remaining = max(0, self.profiles[aid]["mission_details"]["duration_days"] - (self.mission_day(aid) or 1) + 1)
        return {"key": key, "status": "projected", "kind": "projection", "basis": basis,
            "current_total": current, "daily_rate": rate, "unit": rule["unit"], "horizon_days": horizon,
            "projected_total": current + rate * horizon, "threshold": limit, "days_to_threshold": days,
            "crosses_within_horizon": current + rate * horizon > limit,
            "mission_remaining_days": remaining, "projected_mission_end_total": current + rate * remaining,
            "assumption": "Conditional constant-rate extrapolation; future exposure may change. This is not a current alarm.",
            "reference_time": iso(at or self._now())}

    def forecast(self, aid, payload):
        with self.lock:
            self._profile(aid)
            if not isinstance(payload, dict):
                raise ValueError("Forecast scenario must be an object")
            key = payload.get("key")
            rule = self.kb.signals.get(key)
            if not rule or rule.get("category") != "radiation":
                raise ValueError("Forecast requires a configured radiation quantity")
            if payload.get("unit") != rule["unit"]:
                raise ValueError("Forecast unit must match the configured dose quantity")
            rate = number(payload.get("daily_rate"), "Daily rate", minimum=0)
            horizon = number(payload.get("horizon_days", 21), "Horizon", minimum=0)
            if horizon > 3650:
                raise ValueError("Forecast horizon must not exceed 3650 days")
            current, reason, _ = self._known_total(aid, self.active_source[aid], key)
            if current is None:
                return {"key": key, "status": "insufficient_data", "kind": "projection", "reason": reason,
                    "assumption": "A future rate alone cannot establish the present exposure total"}
            if rule.get("window") in {"30_days", "1_year"}:
                return {"key": key, "status": "insufficient_data", "kind": "projection",
                    "reason": "Rolling-window forecasts require age-resolved exposure, not a single window total"}
            return self._projection(aid, key, current, rate, horizon, "manual_scenario")

    def close(self):
        with self.lock:
            if self.closed:
                return
            for stat in self.pending.values():
                self.storage.save_daily(stat["session_id"], stat["key"], stat["unit"], self._stat_export(stat))
            self.pending.clear()
            self.storage.close()
            self.closed = True
