"""Generate Lucide-style toolbar SVG icons for nexusslicer-viewer."""
from pathlib import Path

icons_dir = Path(r'C:\Users\User\source\repos\nexusslicer-viewer\media\icons')
icons_dir.mkdir(parents=True, exist_ok=True)

ICONS = {
    'open-viewer': [
        'M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z',
        'M3.27 6.96 12 12.01l8.73-5.05',
        'M12 22.08V12',
    ],
    'uv-mode': ['M3 3h18v18H3z', 'M3 9h18', 'M3 15h18', 'M9 3v18', 'M15 3v18'],
    'connect': [
        'M8 12.5a4.5 4.5 0 0 1 9 0',
        'M4.929 9.929a9 9 0 0 1 14.142 0',
        'M12 17h.01',
        'M1.929 6.929a13 13 0 0 1 20.142 0',
    ],
    'disconnect': [
        'M1 1l22 22',
        'M16.72 11.06A10.94 10.94 0 0 1 19 12.55',
        'M5 12.55a10.94 10.94 0 0 1 5.17-2.39',
        'M10.71 5.05A16 16 0 0 1 22.56 9',
        'M1.42 9a15.91 15.91 0 0 1 4.7-2.88',
        'M8.53 16.11A6 6 0 0 1 12 15',
        'M12 20h.01',
    ],
    'import': [
        'M12 2v10',
        'M17 7l-5 5-5-5',
        'M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4',
    ],
    'license-key': [
        'M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0 3 3L22 7l-3-3m-3.5 3.5L19 4',
    ],
    'license-status': [
        'M20 13.5V7l-8-5-8 5v6c0 5 8 8 8 8s8-3 8-8z',
        'M8 11l3 3 5-5',
    ],
    'analyze-stress': ['M22 12h-4l-3 9L9 3l-3 9H2'],
    'run-texture': [
        'M9.06 11.9l8.07-8.06a2.85 2.85 0 1 1 4.03 4.03l-8.06 8.08',
        'M7.07 14.94c-1.66 0-3 1.35-3 3.02 0 1.33-2.5 1.52-2 2.02 1 1 6.98 1 6.98-1 0-4.17-2.98-5.04-4.98-5.04z',
    ],
    'record-outcome': [
        'M9 11l3 3 8-8',
        'M20 12v6a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h9',
    ],
    'support-regions': [
        'M12 2 2 22h20L12 2z',
        'M12 8v7',
        'M12 17h.01',
    ],
}

ATTRS = 'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"'

count = 0
for name, paths in ICONS.items():
    for theme, colour in [('dark', '#cccccc'), ('light', '#424242')]:
        body = ''.join(f'<path d="{d}" />' for d in paths)
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
            f'width="16" height="16" {ATTRS} style="color:{colour}">{body}</svg>'
        )
        (icons_dir / f'{name}-{theme}.svg').write_text(svg, encoding='utf-8')
        count += 1

print(f'Icons written: {len(ICONS)} commands × 2 themes = {count} SVGs to {icons_dir}')
