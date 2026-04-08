"""Compatibility client for OpenEnv CLI packaging checks."""

from openenv.core.generic_client import GenericAction, GenericEnvClient


class SREIncidentTriageEnvClient(GenericEnvClient):
    """Generic OpenEnv client for interacting with the SRE Incident Triage server."""


__all__ = ["GenericAction", "SREIncidentTriageEnvClient"]

