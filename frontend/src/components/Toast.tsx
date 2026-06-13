import { CheckmarkCircleRegular } from "@fluentui/react-icons"

interface Props {
  msg: string
}

export function Toast({ msg }: Props) {
  return (
    <div className={`toast${msg ? " show" : ""}`} role="status" aria-live="polite">
      <CheckmarkCircleRegular className="h-4 w-4 toast-icon" />
      <span>{msg}</span>
    </div>
  )
}
