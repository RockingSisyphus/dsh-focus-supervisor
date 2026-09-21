"""Compose action groups for the shared JSON executor."""
from . import ui,model,fixture,desktop,backend

def registry(scenario):
    result={}
    for group in (ui,model,fixture,desktop,backend):result.update(group.registry(scenario))
    return result
