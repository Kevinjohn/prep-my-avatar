export default function LabeledConfigField({ label, value, placeholder, onChange, className }) {
  return (
    <label className="block text-sm">
      <span className="font-medium text-content">{label}</span>
      <input className={className} value={value ?? ''} placeholder={placeholder}
        aria-label={label} onChange={(event) => onChange(event.target.value)} />
    </label>
  )
}
