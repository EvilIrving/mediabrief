import { NavLink } from "react-router-dom"
import { WeatherMoonRegular, WeatherSunnyRegular } from "@fluentui/react-icons"
import { Button } from "@/components/ui/button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useTheme } from "@/context/ThemeContext"
import { useI18n } from "@/i18n/I18nContext"

const iconDark = `${import.meta.env.BASE_URL}icon_dark.svg`
const iconLight = `${import.meta.env.BASE_URL}icon_light.svg`

const tabClass = ({ isActive }: { isActive: boolean }) =>
  `tab-nav-btn${isActive ? " active" : ""}`

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
          <span>{t("nav_transcribe")}</span>
        </NavLink>
        <NavLink className={tabClass} to="/download">
          <span>{t("nav_download")}</span>
        </NavLink>
        <NavLink className={tabClass} to="/rss">
          RSS
        </NavLink>
        <NavLink className={tabClass} to="/history">
          <span>{t("nav_history")}</span>
        </NavLink>
      </div>

      <div className="nav-actions">
        <Button
          variant="ghost"
          size="icon"
          title={t("toggle_theme")}
          onClick={toggleTheme}
        >
          {theme === "light" ? <WeatherMoonRegular className="h-4 w-4" /> : <WeatherSunnyRegular className="h-4 w-4" />}
        </Button>

        <Select value={lang} onValueChange={setLang}>
          <SelectTrigger className="w-[110px] h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {languages.map((l) => (
              <SelectItem key={l.code} value={l.code}>
                {l.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </nav>
  )
}
