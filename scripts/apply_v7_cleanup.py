# Made in cooperation with ChatGPT
"""Run from project root after extracting v7 overlay; never modifies database."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RETIRED = (
    'tests/test_radiation_reliability.py',
    'tests/test_radiation_dosimetry.py',
    'tests/test_radiation_pipeline_v4.py',
    'tests/test_nasa_radiation_categories.py',
    'tests/test_nasa_radiation_v6.py',
    'src/astro_health/radiation_dosimetry.py',
    'examples/demo_radiation_types.jsonl',
)

def main():
    for name in RETIRED:
        source = ROOT / name
        if not source.is_file():
            continue
        dest = source.with_name(source.name + '.retired')
        if dest.exists():
            print(f'Skipped {source.relative_to(ROOT)}: .retired backup exists')
            continue
        source.rename(dest)
        print(f'Retired {name} -> {dest.name}')
    print('No database or raw logs were modified.')

if __name__ == '__main__':
    main()
