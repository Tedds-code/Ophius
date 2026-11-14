# Made in cooperation with ChatGPT
# File: src/astro_health/radiation.py
"""Strict NASA-aligned radiation packet validation; no particle/count modes."""
from dataclasses import dataclass

RADIATION_SOURCES = ('unknown', 'gcr', 'spe', 'nuclear_technology', 'other')
ENVIRONMENTS = ('unspecified', 'free_space', 'planetary_surface', 'leo')
MEASUREMENT_BASIS = ('nasa_effective_dose_model',)
NASA_MEASUREMENT_FIELDS = {
    'cumulative_effective_dose': ('career_effective_dose', 'mSv'),
    'daily_gcr_dose_rate': ('gcr_effective_dose_rate', 'mSv/day'),
    'solar_event_dose': ('spe_effective_dose', 'mSv'),
    'nuclear_source_dose': ('nuclear_effective_dose', 'mSv'),
    'lens_dose': ('lens_dose', 'mGy-Eq'),
    'skin_dose': ('skin_dose', 'mGy-Eq'),
    'bfo_dose': ('bfo_dose', 'mGy-Eq'),
}

@dataclass(frozen=True)
class RadiationSpecification:
    radiation_source: str
    environment: str
    measurement_basis: str


def radiation_specification(packet):
    """Require established NASA-aligned quantities, never infer from counts."""
    from astro_health.sensor_processing import ProcessingError
    if packet.sensor not in ('radiation', 'radiation_environment'):
        raise ProcessingError('Expected a radiation sensor packet')
    data = packet.data
    permitted = {'radiation_source', 'environment', 'measurement_basis',
                 *NASA_MEASUREMENT_FIELDS}
    unknown = set(data) - permitted
    if unknown:
        raise ProcessingError(f'Unsupported radiation fields: {sorted(unknown)}')
    source = data.get('radiation_source', 'unknown')
    environment = data.get('environment', 'unspecified')
    basis = data.get('measurement_basis')
    if not isinstance(source, str) or source not in RADIATION_SOURCES:
        raise ProcessingError(f'Unsupported radiation_source: {source!r}')
    if not isinstance(environment, str) or environment not in ENVIRONMENTS:
        raise ProcessingError(f'Unsupported environment: {environment!r}')
    if basis != 'nasa_effective_dose_model':
        raise ProcessingError('Radiation quantities require measurement_basis=nasa_effective_dose_model')
    quantities = set(data).intersection(NASA_MEASUREMENT_FIELDS)
    if not quantities:
        raise ProcessingError('Radiation packet must include a NASA-aligned dose quantity')
    crew_fields = set(NASA_MEASUREMENT_FIELDS) - {'daily_gcr_dose_rate'}
    if packet.sensor == 'radiation_environment':
        if quantities != {'daily_gcr_dose_rate'}:
            raise ProcessingError('Environment sensor accepts only daily_gcr_dose_rate')
        if source != 'gcr':
            raise ProcessingError('daily_gcr_dose_rate requires radiation_source=gcr')
        if environment not in ('free_space', 'planetary_surface'):
            raise ProcessingError('GCR environment must be free_space or planetary_surface')
    else:
        if not quantities.issubset(crew_fields):
            raise ProcessingError('daily_gcr_dose_rate requires radiation_environment')
        if environment not in ('unspecified', 'leo', 'free_space', 'planetary_surface'):
            raise ProcessingError('Invalid crew environment')
    if 'solar_event_dose' in quantities and source != 'spe':
        raise ProcessingError('solar_event_dose requires radiation_source=spe')
    if 'nuclear_source_dose' in quantities and source != 'nuclear_technology':
        raise ProcessingError('nuclear_source_dose requires radiation_source=nuclear_technology')
    if source == 'spe' and quantities - {'solar_event_dose'}:
        raise ProcessingError('SPE packet must contain only solar_event_dose')
    if source == 'nuclear_technology' and quantities - {'nuclear_source_dose'}:
        raise ProcessingError('Nuclear packet must contain only nuclear_source_dose')
    return RadiationSpecification(source, environment, basis)
