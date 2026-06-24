from pydantic import BaseModel
from typing import List

class ClusterResult(BaseModel):
    cluster_id: int
    data_points: List[str]
