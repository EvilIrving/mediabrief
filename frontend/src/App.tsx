import { useEffect } from 'react'
import { HashRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { IconSprite } from '@/components/IconSprite'
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

/* The RSS and History pages use a full-height split layout; the original
   app toggled body.list-page-active for them. */
function Layout() {
  const location = useLocation()
  const isListPage = location.pathname === '/rss' || location.pathname === '/history'

  useEffect(() => {
    document.body.classList.toggle('list-page-active', isListPage)
    return () => document.body.classList.remove('list-page-active')
  }, [isListPage])

  return (
    <>
      <Navbar />
      <main className="main">
        <Routes>
          <Route path="/transcribe" element={<TranscribePage />} />
          <Route path="/download" element={<DownloadPage />} />
          <Route path="/rss" element={<RssPage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="*" element={<Navigate to="/transcribe" replace />} />
        </Routes>
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
              <IconSprite />
              <Layout />
            </HashRouter>
          </TaskHandoffProvider>
        </SettingsProvider>
      </I18nProvider>
    </ThemeProvider>
  )
}
