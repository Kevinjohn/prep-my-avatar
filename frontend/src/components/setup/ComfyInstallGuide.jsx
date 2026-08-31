import CopyCommand from './CopyCommand'

export default function ComfyInstallGuide({ platform = '', app = { launchCommand: '' }, expanded = false }) {
  const isMac = platform === 'darwin'
  const isWindows = platform === 'win32'
  const venvCommand = isWindows ? 'python -m venv .venv' : 'python3 -m venv .venv'
  const activateCommand = isWindows ? String.raw`.\.venv\Scripts\activate` : 'source .venv/bin/activate'

  return (
    <details open={expanded}
      className="rounded-md border border-border bg-surface-raised px-3 py-2 text-sm text-content-muted">
      <summary className="cursor-pointer font-medium text-content">
        Installation options: Comfy Desktop or Git/manual
      </summary>
      <div className="mt-3 space-y-3">
        <p className="font-medium text-content">Choose one installation method</p>
        <div className="grid gap-3 lg:grid-cols-2">
          <section aria-labelledby="comfy-desktop-install"
            className="rounded-md border border-border bg-surface px-3 py-3">
            <div className="flex flex-wrap items-center gap-2">
              <h3 id="comfy-desktop-install" className="font-semibold text-content">Comfy Desktop</h3>
              <span className="rounded bg-primary/15 px-1.5 py-0.5 text-[11px] text-primary">
                Recommended on macOS and Windows
              </span>
            </div>
            <ol className="mt-2 list-decimal space-y-2 pl-5 text-xs">
              <li>
                <a href="https://www.comfy.org/download" target="_blank" rel="noreferrer"
                  className="text-primary underline">Download Comfy Desktop →</a>
              </li>
              <li>
                Install and open it.{app.launchCommand && <><span> On this Mac:</span>
                  <CopyCommand command={app.launchCommand} /></>}
              </li>
              <li>
                Create or select an instance. Opening Comfy Desktop alone does not start its server: on the
                dashboard, click the instance card to start it.
              </li>
              <li>
                In the instance menu, open <strong className="text-content">Storage</strong>. Copy the
                instance’s <strong className="text-content">application directory</strong> into the
                ComfyUI install directory field below. Do not use the path to the Desktop app itself.
              </li>
              <li>
                Wait for the instance interface to load, then select
                {' '}<strong className="text-content">Save &amp; re-check</strong>.
              </li>
            </ol>
          </section>

          <section aria-labelledby="comfy-git-install"
            className="rounded-md border border-border bg-surface px-3 py-3">
            <h3 id="comfy-git-install" className="font-semibold text-content">Git / manual installation</h3>
            <p className="mt-1 text-xs">
              Use this when you deliberately want to own the clone, Python environment, updates, and Terminal process.
            </p>
            <ol className="mt-2 list-decimal space-y-2 pl-5 text-xs">
              <li>Clone ComfyUI:<CopyCommand command="git clone https://github.com/comfyanonymous/ComfyUI" /></li>
              <li>Enter the clone:<CopyCommand command="cd ComfyUI" /></li>
              <li>Create an isolated Python environment:<CopyCommand command={venvCommand} /></li>
              <li>Activate it:<CopyCommand command={activateCommand} /></li>
              {isMac && (
                <li>
                  Apple Silicon requires an MPS-capable PyTorch build. The official ComfyUI instructions currently
                  recommend the latest PyTorch nightly before installing the remaining dependencies.{' '}
                  <a href="https://github.com/comfyanonymous/ComfyUI#apple-mac-silicon"
                    target="_blank" rel="noreferrer" className="text-primary underline">
                    Official Apple Silicon note →
                  </a>
                </li>
              )}
              <li>Install ComfyUI’s dependencies:<CopyCommand command="python -m pip install -r requirements.txt" /></li>
              <li>Start the server and leave Terminal open:
                <CopyCommand command="python main.py --listen 127.0.0.1 --port 8188" />
              </li>
              <li>Enter this clone’s full folder path below, then select <strong className="text-content">Save &amp; re-check</strong>.</li>
            </ol>
          </section>
        </div>
      </div>
    </details>
  )
}
