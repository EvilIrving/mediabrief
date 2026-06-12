import { ErrorCircleRegular, KeyRegular } from "@fluentui/react-icons"

interface Props {
  msg: string
  notice?: boolean
}

export function ErrorBanner({ msg, notice = false }: Props) {
  return (
    <div className={`error-banner${msg ? " show" : ""}${notice ? " notice" : ""}`}>
      {notice ? (
        <KeyRegular className="h-4 w-4 banner-icon" />
      ) : (
        <ErrorCircleRegular className="h-4 w-4 banner-icon" />
      )}
      <span>{msg}</span>
    </div>
  )
}
