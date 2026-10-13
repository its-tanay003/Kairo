import re, sys

files = [
    'ui/src/app/components/AuditExplorer.tsx',
    'ui/src/app/components/BenchmarkLeaderboard.tsx',
    'ui/src/app/components/DatasetCurationPanel.tsx'
]

for f in files:
    with open(f, 'r', encoding='utf-8') as fp:
        content = fp.read()
        raw_classes = re.findall(r'className=["\']([^"\']+)["\']', content)
        template_classes = re.findall(r'className=\{`([^`]+)`\}', content)
        all_classes = set()
        for rc in raw_classes:
            for item in rc.split():
                all_classes.add(item)
        for tc in template_classes:
            # strip template exprs
            cleaned = re.sub(r'\$\{[^}]+\}', '', tc)
            for item in cleaned.split():
                all_classes.add(item)
        print(f"=== {f} ({len(all_classes)} classes) ===")
        print(sorted(list(all_classes)))
