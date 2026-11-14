# Made in cooperation with ChatGPT
# File: scripts/convert_radiation_csv.py
"""Convert ALREADY CHARACTERIZED radiation CSV columns to option-5 JSONL.

This is NOT a generic NASA PDS reader. Inspect each archive's metadata first.
Only explicitly mapped equivalent dose (Sv-family) or detector counts are
supported. Absorbed dose (Gy), LET and count rate (counts/s) cannot be safely
mapped to Sv or integrated counts by guessing calibration/units.
"""
import argparse
import csv
from datetime import datetime
import math
import os
from pathlib import Path
import tempfile

from astro_health.sensor_packets import SensorPacket


def nonnegative(text, label):
    try:
        result = float(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{label} must be numeric: {text!r}') from exc
    if not math.isfinite(result) or result < 0:
        raise ValueError(f'{label} must be nonnegative and finite')
    return result


def convert(args):
    source, target = Path(args.input).resolve(), Path(args.output).resolve()
    if source == target:
        raise ValueError('Input and output must be different files')
    if target.exists():
        raise ValueError(f'Output exists; refusing to overwrite: {target}')
    if not any((args.rate_column, args.dose_column, args.counts_column)):
        raise ValueError('Map at least one rate/dose/counts column')
    if args.rate_column and not args.rate_unit:
        raise ValueError('--rate-unit is required; do not guess source units')
    if args.dose_column and (not args.dose_unit or not args.dose_mode):
        raise ValueError('--dose-unit and --dose-mode are required')
    if args.counts_column and not args.count_mode:
        raise ValueError('--count-mode is required for detector counts')
    if (args.dose_mode == 'interval' or args.count_mode == 'interval') and not args.interval_column:
        raise ValueError('Interval readings require --interval-column')
    if args.interval_column and args.dose_mode != 'interval' and args.count_mode != 'interval':
        raise ValueError('An interval column requires an interval measurement')
    rate_multiplier = {'uSv/h': 1.0, 'mSv/h': 1000.0}.get(args.rate_unit)
    dose_multiplier = {'uSv': 1.0, 'mSv': 1000.0}.get(args.dose_unit)
    if args.rate_column and rate_multiplier is None:
        raise ValueError('Only uSv/h and mSv/h supported. Gy cannot be converted to Sv without radiation weighting')
    if args.dose_column and dose_multiplier is None:
        raise ValueError('Only uSv and mSv supported. Gy cannot be converted to Sv without radiation weighting')

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = None
    count = 0
    try:
        with source.open('r', newline='', encoding='utf-8-sig') as inp:
            reader = csv.DictReader(inp)
            required = {args.timestamp_column} | {
                v for v in (args.rate_column, args.dose_column,
                            args.counts_column, args.interval_column) if v
            }
            if not required.issubset(reader.fieldnames or ()):
                raise ValueError(f'CSV columns missing: {sorted(required - set(reader.fieldnames or []))}')
            with tempfile.NamedTemporaryFile('w', encoding='utf-8', newline='\n',
                                             dir=target.parent, prefix='.radiation_',
                                             suffix='.tmp', delete=False) as out:
                tmp_path = Path(out.name)
                for line_number, row in enumerate(reader, start=2):
                    try:
                        stamp = datetime.fromisoformat(row[args.timestamp_column].strip().replace('Z', '+00:00'))
                        if stamp.utcoffset() is None:
                            raise ValueError('Timestamp must contain a timezone offset')
                        data = {}
                        if args.rate_column:
                            data['dose_rate_uSv_h'] = nonnegative(
                                row[args.rate_column], 'dose rate') * rate_multiplier
                        if args.dose_column:
                            data['dose_uSv'] = nonnegative(row[args.dose_column], 'dose') * dose_multiplier
                            data['dose_mode'] = args.dose_mode
                        if args.counts_column:
                            val = nonnegative(row[args.counts_column], 'counts')
                            if not val.is_integer():
                                raise ValueError('counts must be a whole number, not count rate')
                            data['counts'] = int(val)
                            data['count_mode'] = args.count_mode
                        if args.interval_column:
                            interval = nonnegative(row[args.interval_column], 'interval_seconds')
                            if not 0 < interval <= 86400:
                                raise ValueError('interval_seconds must be > 0 and <= 86400')
                            data['interval_seconds'] = interval
                        packet = SensorPacket(
                            sensor='radiation', timestamp=stamp, origin='replay',
                            device_id=args.device_id, calibration_id=args.calibration_id,
                            data=data,
                        )
                        # Run exactly the same semantics checker used by CLI ingestion.
                        from astro_health.radiation import radiation_specification
                        radiation_specification(packet)
                        out.write(packet.to_json() + '\n')
                        count += 1
                    except Exception as exc:
                        raise ValueError(f'CSV line {line_number}: {exc}') from exc
        if not count:
            raise ValueError('CSV contains no data rows')
        # Atomic publication WITHOUT overwrite even under concurrent writers.
        # Temporary file lives in the target directory (same filesystem).
        os.link(tmp_path, target)
        tmp_path.unlink()
        tmp_path = None
        return count
    finally:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink()


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, help='Exported CSV input')
    parser.add_argument('--output', required=True, help='New option-5 JSONL output')
    parser.add_argument('--timestamp-column', required=True)
    parser.add_argument('--rate-column')
    parser.add_argument('--rate-unit', choices=('uSv/h', 'mSv/h'))
    parser.add_argument('--dose-column')
    parser.add_argument('--dose-unit', choices=('uSv', 'mSv'))
    parser.add_argument('--dose-mode', choices=('interval', 'cumulative'))
    parser.add_argument('--counts-column')
    parser.add_argument('--count-mode', choices=('interval', 'cumulative'))
    parser.add_argument('--interval-column', help='Actual duration in seconds')
    parser.add_argument('--device-id', required=True)
    parser.add_argument('--calibration-id')
    return parser


if __name__ == '__main__':
    args = build_parser().parse_args()
    try:
        print(f'Converted {convert(args)} radiation rows to {args.output}')
    except (ValueError, OSError) as exc:
        raise SystemExit(f'Conversion failed: {exc}') from exc
