"""Repository-root entry point for the independently installable agent skill."""
from pathlib import Path
import runpy

if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).resolve().parents[1] / '.agents/skills/jingliu-video/scripts/jingliu.py'), run_name='__main__')
