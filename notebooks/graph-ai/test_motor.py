"""Tests del motor de inferencia del grafo ponderado.

Corren sin LLM (milisegundos): `pytest test_motor.py -v` desde notebooks/graph-ai/.
Los snapshots de decisión están validados a mano contra el visualizador (grafo_vivia.html)
y anclados a año_actual=2026 para que no caduquen con el calendario.
"""

import shutil
from pathlib import Path

import pytest
from motor_inferencia import (
    activar,
    buckets_de,
    cargar_dominio,
    cargar_drafts,
    inferir,
    resumen_para_llm,
)

BASE = Path(__file__).parent
AÑO = 2026


@pytest.fixture(scope="module")
def dominio():
    return cargar_dominio(BASE / "datasets")


@pytest.fixture(scope="module")
def drafts(dominio):
    return {d["id"]: d for d in cargar_drafts(BASE / "datasets" / "drafts_ejemplo.json")}


def draft_sintetico(**cambios) -> dict:
    base = {
        "id": "sintetico", "propertyType": {"id": "x", "name": "CASA"},
        "address": {"neighborhoodName": "Centro"}, "availableToRent": True,
        "areaM2": 120, "bedrooms": 3, "bathrooms": 2, "parkingSpaces": 1,
        "constructionYear": 2015, "condominium": False, "listedPrice": 1,
        "amenities": [],
    }
    base.update(cambios)
    return base


# ─── Tests de decisión (snapshots sobre los 7 drafts reales) ─────────────────

def test_draft_001_casa_renta_estrenar(dominio, drafts):
    d = inferir(dominio, drafts["draft-001"], año_actual=AÑO)
    assert d.temas == ["vida_al_aire_libre", "convivencia_familiar"]
    assert d.audiencia == "familia_grande"
    assert d.protagonistas == ["Terraza", "Jardín"]
    assert d.secundarias == ["Gimnasio"]  # "GYM" resuelto por alias
    assert "a estrenar" in d.hechos and "superficie amplia" in d.hechos
    assert d.desconocidas == []


def test_draft_004_compacto_amueblado(dominio, drafts):
    d = inferir(dominio, drafts["draft-004"], año_actual=AÑO)
    assert d.temas == ["flexibilidad", "practicidad"]  # Amueblado + RENTA empujan flexibilidad
    assert d.audiencia == "profesionista"
    assert "convivencia_familiar" in d.bloqueados  # area_compacta la bloquea


def test_draft_005_sin_amenidades(dominio, drafts):
    d = inferir(dominio, drafts["draft-005"], año_actual=AÑO)
    assert d.temas == ["convivencia_familiar", "tranquilidad"]  # solo priors de CASA
    assert d.protagonistas == []
    assert d.audiencia == "familia_pareja"


def test_draft_006_amenidad_desconocida(dominio, drafts):
    d = inferir(dominio, drafts["draft-006"], año_actual=AÑO)
    assert d.desconocidas == ["Sala de cine"]
    assert "Área de Juegos Infantiles" in d.protagonistas


def test_draft_007_local_comercial(dominio, drafts):
    d = inferir(dominio, drafts["draft-007"], año_actual=AÑO)
    assert d.temas == ["seguridad", "funcionalidad_comercial"]
    assert d.audiencia == "negocio_emprendedor"
    assert {"convivencia_familiar", "tranquilidad"} <= set(d.bloqueados)
    assert "no mencionar estacionamientos" in d.hechos  # parkingSpaces = 0


# ─── Tests de bloqueo (exhaustivos: la calle en contra jamás se toma) ────────

TIPOS_COMERCIALES = ["Local Comercial", "Oficina", "Bodega"]
AMENIDADES_EMPUJE = [
    [], ["Amueblado"], ["Jardín", "Área de BBQ", "Área de Juegos Infantiles"],
    ["Alberca", "Terraza", "Amueblado", "Semi-Amueblado"],
]


@pytest.mark.parametrize("amenities", AMENIDADES_EMPUJE)
@pytest.mark.parametrize("tipo", ["CASA", "DEPARTAMENTO", "Terreno"] + TIPOS_COMERCIALES)
def test_venta_jamas_flexibilidad(dominio, tipo, amenities):
    d = draft_sintetico(availableToRent=False, amenities=amenities,
                        propertyType={"id": "x", "name": tipo})
    assert "flexibilidad" not in inferir(dominio, d, año_actual=AÑO).temas


@pytest.mark.parametrize("tipo", ["CASA", "DEPARTAMENTO", "Terreno"] + TIPOS_COMERCIALES)
def test_renta_jamas_patrimonio(dominio, tipo):
    d = draft_sintetico(availableToRent=True, propertyType={"id": "x", "name": tipo})
    assert "patrimonio" not in inferir(dominio, d, año_actual=AÑO).temas


@pytest.mark.parametrize("amenities", AMENIDADES_EMPUJE)
@pytest.mark.parametrize("renta", [True, False])
@pytest.mark.parametrize("tipo", TIPOS_COMERCIALES)
def test_comercial_jamas_convivencia(dominio, tipo, renta, amenities):
    d = draft_sintetico(propertyType={"id": "x", "name": tipo}, availableToRent=renta,
                        amenities=amenities)
    assert "convivencia_familiar" not in inferir(dominio, d, año_actual=AÑO).temas


def test_con_historia_jamas_estilo_moderno(dominio):
    d = draft_sintetico(constructionYear=1980, amenities=["Roof Garden"],
                        propertyType={"id": "x", "name": "DEPARTAMENTO"})
    dec = inferir(dominio, d, año_actual=AÑO)
    assert "estilo_moderno" not in dec.temas
    assert "estilo_moderno" in dec.bloqueados


# ─── Activación y resumen ────────────────────────────────────────────────────

def test_buckets(dominio):
    d = draft_sintetico(constructionYear=2026, areaM2=200, bedrooms=4,
                        condominium=True, parkingSpaces=0)
    assert set(buckets_de(d, año_actual=AÑO)) == {
        "a_estrenar", "area_amplia", "rec_4_mas", "en_condominio", "sin_estacionamiento"}


def test_alias_y_tipo_normalizados(dominio):
    d = draft_sintetico(propertyType={"id": "x", "name": "LOCAL COMERCIAL"},
                        amenities=["GYM", "piscina", "Circuito Cerrado (CCTV)"])
    activos, desconocidas, _, tipo = activar(dominio, d, año_actual=AÑO)
    assert tipo == "Local Comercial"
    assert {"am:gimnasio", "am:alberca", "am:cctv"} <= set(activos)
    assert desconocidas == []


def test_resumen_sin_precio(dominio, drafts):
    for draft in drafts.values():
        dec = inferir(dominio, draft, año_actual=AÑO)
        texto = resumen_para_llm(dominio, draft, dec)
        assert "$" not in texto and str(draft["listedPrice"]) not in texto
        assert texto.startswith("DECISIONES DE REDACCIÓN")


def test_umbral_sin_temas_debiles(dominio):
    # Terreno en venta sin amenidades: solo patrimonio (prior 0.8) supera el umbral.
    d = draft_sintetico(propertyType={"id": "x", "name": "Terreno"},
                        availableToRent=False, bedrooms=0)
    dec = inferir(dominio, d, año_actual=AÑO)
    assert dec.temas == ["patrimonio"]


# ─── Validación de carga (dataset roto falla temprano) ───────────────────────

def _copia_datasets(tmp_path: Path) -> Path:
    destino = tmp_path / "datasets"
    shutil.copytree(BASE / "datasets", destino)
    return destino


def test_carga_falla_peso_fuera_de_escala(tmp_path):
    ds = _copia_datasets(tmp_path)
    contenido = (ds / "pesos_evoca.csv").read_text().replace("0.9", "0.7", 1)
    (ds / "pesos_evoca.csv").write_text(contenido)
    with pytest.raises(ValueError, match="fuera de escala"):
        cargar_dominio(ds)


def test_carga_falla_clave_inexistente(tmp_path):
    ds = _copia_datasets(tmp_path)
    with open(ds / "bloqueos.csv", "a") as f:
        f.write("Castillo,tipo,tranquilidad,tipo que no existe\n")
    with pytest.raises(ValueError, match="origen desconocido"):
        cargar_dominio(ds)


def test_carga_falla_prior_excedido(tmp_path):
    ds = _copia_datasets(tmp_path)
    with open(ds / "pesos_priors.csv", "a") as f:
        f.write("Casa,tipo,bienestar,0.9\n")
    with pytest.raises(ValueError, match="prior"):
        cargar_dominio(ds)
