import { NavLink } from 'react-router-dom'
import { Icon } from './IconSprite'
import { useTheme } from '@/context/ThemeContext'
import { useI18n } from '@/i18n/I18nContext'

/* Logos live in the FastAPI-served /static dir, not in the Vite bundle. */
const iconDark = '/static/icon_dark.svg'
const iconLight = '/static/icon_light.svg'

const tabClass = ({ isActive }: { isActive: boolean }) =>
  `tab-nav-btn${isActive ? ' active' : ''}`

export function Navbar() {
  const { theme, toggleTheme } = useTheme()
  const { t, lang, languages, setLang } = useI18n()

  return (
    <nav className="navbar">
      <NavLink className="nav-logo" to="/transcribe">
        <img className="logo-dark" src={iconDark} alt="logo" />
        <img className="logo-light" src={iconLight} alt="logo" />
        <span className="nav-logo-text">
          AI<em>Transcriber</em>
        </span>
      </NavLink>

      <div className="tab-nav">
        <NavLink className={tabClass} to="/transcribe">
          <span>{t('nav_transcribe')}</span>
        </NavLink>
        <NavLink className={tabClass} to="/download">
          <span>{t('nav_download')}</span>
        </NavLink>
        <NavLink className={tabClass} to="/rss">
          RSS
        </NavLink>
        <NavLink className={tabClass} to="/history">
          <span>{t('nav_history')}</span>
        </NavLink>
      </div>

      <div className="nav-actions">
        <button className="icon-btn" title={t('toggle_theme')} onClick={toggleTheme}>
          <Icon name={theme === 'light' ? 'i-moon' : 'i-sun'} />
        </button>
        <select
          className="icon-btn"
          aria-label={t('ui_language')}
          value={lang}
          onChange={(e) => setLang(e.target.value)}
        >
          {languages.map((l) => (
            <option key={l.code} value={l.code}>
              {l.label}
            </option>
          ))}
        </select>
      </div>
    </nav>
  )
}
