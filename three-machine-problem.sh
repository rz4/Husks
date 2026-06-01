husks init /tmp/husks30beta-live
cd /tmp/husks30beta-live

husks run core-bootstrap.json --site m1 --verbose --report-json m1.json
husks cache export cache.tgz --site m1
husks cache import cache.tgz --site m2
husks run core-bootstrap.json --site m2 --reuse-only --verbose --report-json m2.json
husks run core-bootstrap.json --site m3 --verbose --report-json m3.json
husks compare-runs m1.json m2.json m3.json --json
