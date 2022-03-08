from typing import Any, Dict, Optional

from aws_lambda_powertools import Logger
from horangi.generated.severity_level import SeverityLevel
from pydantic import BaseModel, Field, validator

logger = Logger(child=True)


class DestinationConfiguration(BaseModel):
    """
    DestinationConfiguration models elements in
    ActionGroup.destination_configurations

    TODO: this can replace horangi.destinations.core.DestinationConfiguration
    """

    destination_uid: str
    is_enabled: bool = True
    # NOTE: filters for now only supports severities, e.g.
    #  `"severities": [ 4, 3 ]`
    filters: Optional[Dict[str, Any]] = Field(default_factory=dict)

    @validator("filters")
    def valid_filters(cls, v):
        for k, v_ in v.items():
            if k == "severities":
                for s in v_:
                    SeverityLevel(s)
        return v
