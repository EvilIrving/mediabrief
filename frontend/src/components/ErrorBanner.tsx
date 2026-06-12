import { Icon } from './IconSprite'

/* Error / notice banner. Visible only when `msg` is non-empty. */
export function ErrorBanner({ msg, notice = false }: { msg: string; notice?: boolean }) {
  return (
    <div className={`error-banner${msg ? ' show' : ''}${notice ? ' notice' : ''}`}>
      <Icon name={notice ? 'i-key' : 'i-circle-exclamation'} className="icon banner-icon" />
      <span>{msg}</span>
    </div>
  )
}
