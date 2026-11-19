"""Reading Aula's answer to presence.getPresenceConfigurationByChildIds into the model."""

from typing import List

from ..responses.get_presence_configuration_by_child_ids_response import (
    AulaChildPresenceConfigurationData,
    AulaGetPresenceConfigurationByChildIdsResponse,
)
from .aula_parser import AulaParser
from .aula_presence_models import AulaPresenceConfiguration, AulaPresencePermission

GUARDIAN_DASHBOARD = "guardian_dashboard"
"""The dashboard a guardian sees, as Aula names it."""


class AulaPresenceParser(AulaParser):
    """Reads what a guardian may do in the presence module."""

    @staticmethod
    def parse_response(data: AulaGetPresenceConfigurationByChildIdsResponse) -> List[AulaPresenceConfiguration]:
        """Each child's configuration in Aula's answer."""
        return [AulaPresenceParser.parse_configuration(child) for child in data["data"]]

    @staticmethod
    def parse_configuration(data: AulaChildPresenceConfigurationData) -> AulaPresenceConfiguration:
        """A child's configuration on the guardian's dashboard; a permission Aula names otherwise is taken as deactivated."""
        settings = (data.get("presenceConfiguration") or {}).get("dashboardModuleSettings") or []
        guardian = next((setting for setting in settings if setting.get("presenceDashboardContext") == GUARDIAN_DASHBOARD), None)
        known = {str(permission) for permission in AulaPresencePermission}
        modules: dict[str, AulaPresencePermission] = {}
        for module in ((guardian or {}).get("presenceModules") or []):
            permission = AulaPresenceParser._parse_str(module.get("permission"))
            modules[AulaPresenceParser._parse_str(module.get("moduleType"))] = (
                AulaPresencePermission(permission) if permission in known else AulaPresencePermission.DEACTIVATED
            )
        return AulaPresenceConfiguration(child_id=AulaPresenceParser._parse_int(data.get("uniStudentId")), modules=modules)
