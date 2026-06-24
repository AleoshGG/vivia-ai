from pydantic import BaseModel

# Aquí irían modelos Pydantic comunes que describen metadatos o esquemas
# específicos de los datos que viven en el Data Lake.

class DataLakeObjectMeta(BaseModel):
    """
    Metadatos de un objeto en el Data Lake.
    """
    key: str
    size_bytes: int
    content_type: str
