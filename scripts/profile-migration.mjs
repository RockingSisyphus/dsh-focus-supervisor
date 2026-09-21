import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

export function migrateEntries(entries, configuration = {}) {
  const result = [];
  for (const entry of entries) {
    if (!entry.insert) {
      const override = { ...entry };
      if (override.id === 'focus-supervisor-chat') delete override.name;
      result.push(override);
      continue;
    }
    const retained = [];
    for (const inserted of entry.insert) {
      if (inserted.id !== 'focus-supervisor-chat') {
        retained.push(inserted);
        continue;
      }
      const { name, ...override } = inserted;
      if (Object.keys(override).length > 1) result.push(override);
    }
    if (retained.length) result.push({ ...entry, insert: retained });
  }
  if (Object.keys(configuration).length) result.push({ id: 'focus-supervisor-chat', config: configuration });
  return result;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const yaml = createRequire(process.argv[2])('js-yaml');
  const content = readFileSync(0, 'utf8');
  const entries = yaml.load(content) || [];
  const updated = migrateEntries(entries, JSON.parse(process.argv[3] || '{}'));
  process.stdout.write(JSON.stringify(entries) === JSON.stringify(updated) ? content : yaml.dump(updated));
}
