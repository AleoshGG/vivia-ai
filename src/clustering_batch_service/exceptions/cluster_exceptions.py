from shared.exceptions import BaseServiceException

class ClusteringError(BaseServiceException):
    def __init__(self, message: str):
        super().__init__(message, code="clustering_error")
