import datetime

import numpy as np
import pandas as pd

from ..models.property import Draft

NUMERIC_COLS = [
    'areaM2', 'listedPrice', 'pricePerM2', 'bedrooms', 'bathrooms',
    'parkingSpaces', 'antiguedad', 'condominium', 'n_amenities', 'total_images',
]
LOG_COLS    = ['areaM2', 'listedPrice', 'pricePerM2']
KNOWN_TYPES = ['Bodega', 'Casa', 'Departamento', 'Local Comercial', 'Oficina', 'Terreno']

PROPERTY_TYPE_ID_MAP: dict[str, str] = {
    '550e8400-e29b-41d4-a716-446655440001': 'Casa',
    '550e8400-e29b-41d4-a716-446655440002': 'Departamento',
    '550e8400-e29b-41d4-a716-446655440003': 'Terreno',
    '550e8400-e29b-41d4-a716-446655440004': 'Local Comercial',
    '550e8400-e29b-41d4-a716-446655440005': 'Oficina',
    '550e8400-e29b-41d4-a716-446655440006': 'Bodega',
}


def build_features(draft: Draft, feature_cols: list[str]) -> np.ndarray:
    """Transforma un Draft en el vector de features que espera el modelo.

    Reproduce exactamente el pipeline del notebook 04:
      1. Extrae campos numéricos del Draft (con mapeo de nombres)
      2. Aplica log1p en columnas sesgadas (área, precio)
      3. One-hot encoding de propertyType con 6 columnas fijas
      4. Reordena según feature_cols del artefacto exportado
    """
    current_year = datetime.datetime.now().year

    pt_id   = draft.property_type.id
    pt_name = PROPERTY_TYPE_ID_MAP.get(pt_id, draft.property_type.name)

    row = {
        'areaM2'       : draft.area_m2,
        'listedPrice'  : draft.listed_price,
        'pricePerM2'   : draft.price_per_m2,
        'bedrooms'     : float(draft.bedrooms),
        'bathrooms'    : draft.bathrooms,
        'parkingSpaces': float(draft.parking_spaces),
        'antiguedad'   : float(current_year - draft.construction_year),
        'condominium'  : 1.0 if draft.condominium else 0.0,
        'n_amenities'  : float(len(draft.amenity_ids)),
        'total_images' : float(draft.total_images),
    }

    frame = pd.DataFrame([row])
    frame[LOG_COLS] = np.log1p(frame[LOG_COLS])

    for pt in KNOWN_TYPES:
        frame[f'type_{pt}'] = 1.0 if pt == pt_name else 0.0

    frame = frame.reindex(columns=feature_cols, fill_value=0.0)
    return frame.values  # shape (1, 16)
