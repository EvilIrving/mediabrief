import { useEffect } from 'react'
import { HashRouter, useLocation, useNavigate } from 'react-router-dom'
import { Navbar } from '@/components/Navbar'
import { Footer } from '@/components/Footer'
import { ThemeProvider } from '@/context/ThemeContext'
import { I18nProvider } from '@/i18n/I18nContext'
import { SettingsProvider } from '@/context/SettingsContext'
import { TaskHandoffProvider } from '@/context/TaskHandoff'
import { TranscribePage } from '@/features/transcribe/TranscribePage'
import { DownloadPage } from '@/features/download/DownloadPage'
import { RssPage } from '@/features/rss/RssPage'
import { HistoryPage } from '@/features/history/HistoryPage'

const PAGE_PATHS = ['/transcribe', '/download', '/rss', '/history'] as const

type PagePath = (typeof PAGE_PATHS)[number]

function isPagePath(pathname: string): pathname is PagePath {
  return PAGE_PATHS.includes(pathname as PagePath)
}

/* The RSS and History pages use a full-height split layout; the original
   app toggled body.list-page-active for them. */
function Layout() {
  const location = useLocation()
  const navigate = useNavigate()
  const currentPath = isPagePath(location.pathname) ? location.pathname : '/transcribe'
  const isListPage = currentPath === '/rss' || currentPath === '/history'

  useEffect(() => {
    if (!isPagePath(location.pathname)) navigate('/transcribe', { replace: true })
  }, [location.pathname, navigate])

  useEffect(() => {
    document.body.classList.toggle('list-page-active', isListPage)
    return () => document.body.classList.remove('list-page-active')
  }, [isListPage])

  return (
    <>
      <Navbar />
      <main className="main">
        <div className="route-page" hidden={currentPath !== '/transcribe'}>
          <TranscribePage />
        </div>
        <div className="route-page" hidden={currentPath !== '/download'}>
          <DownloadPage />
        </div>
        <div className="route-page" hidden={currentPath !== '/rss'}>
          <RssPage />
        </div>
        <div className="route-page" hidden={currentPath !== '/history'}>
          <HistoryPage />
        </div>
      </main>
      <Footer />
    </>
  )
}

export default function App() {
  return (
    <ThemeProvider>
      <I18nProvider>
        <SettingsProvider>
          <TaskHandoffProvider>
            <HashRouter>
              <Layout />
            </HashRouter>
          </TaskHandoffProvider>
        </SettingsProvider>
      </I18nProvider>
    </ThemeProvider>
  )
}
