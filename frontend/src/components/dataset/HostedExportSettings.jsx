const FIELD = 'w-full rounded border border-border bg-surface px-2 py-1.5 text-sm text-content';

export default function HostedExportSettings({ draft, recipes, onChange }) {
  const changeSubject = (patch) => onChange({ subject: { ...draft.subject, ...patch } });
  const changeParameter = (name, value) => onChange({ parameters: { ...draft.parameters, [name]: value } });
  const recipe = recipes.find((item) => item.id === draft.recipe_id && item.version === draft.recipe_version);
  return <div className="flex flex-col gap-3">
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="text-sm text-content-muted">Hosted subject name<input className={FIELD} value={draft.subject.name} onChange={(event) => changeSubject({ name: event.target.value })} /></label>
      <label className="text-sm text-content-muted">Hosted trigger word<input className={FIELD} value={draft.subject.trigger_word} onChange={(event) => changeSubject({ trigger_word: event.target.value })} /></label>
      <label className="text-sm text-content-muted">Rights basis<select className={FIELD} value={draft.subject.rights_basis} onChange={(event) => changeSubject({ rights_basis: event.target.value })}>
        <option value="">Choose a rights basis</option><option value="owned">Owned</option><option value="licensed">Licensed</option><option value="consented">Permission / consent</option><option value="public-domain">Public domain</option>
      </select></label>
      <label className="text-sm text-content-muted">Publication scope<input className={FIELD} value={draft.subject.publication_scope} onChange={(event) => changeSubject({ publication_scope: event.target.value })} placeholder="Private preparation; intended website and slide use…" /></label>
    </div>
    <label className="flex items-start gap-2 text-sm text-content"><input type="checkbox" checked={draft.subject.consent} onChange={(event) => changeSubject({ consent: event.target.checked })} />I have consent from every identifiable person for the selected processing and intended use.</label>
    <label className="text-sm text-content-muted">Hosted recipe<select className={FIELD} value={`${draft.recipe_id}:${draft.recipe_version}`} onChange={(event) => {
      const selected = recipes.find((item) => `${item.id}:${item.version}` === event.target.value);
      onChange({ recipe_id: selected.id, recipe_version: selected.version, parameters: { ...selected.defaults } });
    }}>{recipes.map((item) => <option key={`${item.id}:${item.version}`} value={`${item.id}:${item.version}`}>{item.name} · version {item.version}</option>)}</select></label>
    <div className="grid gap-3 sm:grid-cols-3">
      {Object.entries(recipe?.parameters || {}).map(([name, rule]) => {
        const label = { resolution: 'Hosted resolution', steps: 'Training steps', learning_rate: 'Learning rate', auto_captioning: 'Auto-captioning', debug_dataset: 'Request prepared dataset from a later manual trainer run' }[name] || name.replaceAll('_', ' ');
        const value = draft.parameters[name];
        if (rule.type === 'boolean') return <label key={name} className="flex items-start gap-2 text-sm text-content"><input type="checkbox" checked={Boolean(value)} onChange={(event) => changeParameter(name, event.target.checked)} />{label}</label>;
        return <label key={name} className="text-sm text-content-muted">{label}
          {rule.enum ? <select className={FIELD} value={value} onChange={(event) => changeParameter(name, rule.type === 'integer' || rule.type === 'number' ? Number(event.target.value) : event.target.value)}>{rule.enum.map((option) => <option key={String(option)} value={option}>{String(option)}</option>)}</select>
            : <input className={FIELD} type={rule.type === 'integer' || rule.type === 'number' ? 'number' : 'text'} min={rule.minimum} max={rule.maximum} step={rule.type === 'integer' ? 1 : 'any'} value={value ?? ''} onChange={(event) => changeParameter(name, rule.type === 'integer' || rule.type === 'number' ? Number(event.target.value) : event.target.value)} />}
        </label>;
      })}
    </div>
    <p className="m-0 text-xs text-content-subtle">These recipe settings describe a later manual run. Downloading this package performs no upload, training or paid provider call.</p>
  </div>;
}
