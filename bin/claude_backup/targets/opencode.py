from pathlib import Path
from . import Target, register
from .. import common

@register
class _Stub(Target):
    name = "opencode"

    def skills_dir(self) -> Path: return common.home() / f".{self.name}" / "skills"
    def mcp_plan(self, g, p, *, force): return []
    def write_mcp(self, g, p, *, force, dry): return []
    def read_mcp_names(self): return set()
