interface ErrorBannerProps {
  title: string
  message: string
  dismissible?: boolean
  onDismiss?: () => void
}

export function ErrorBanner({ title, message, dismissible = true, onDismiss }: ErrorBannerProps) {
  return (
    <div className={`error-banner ${dismissible ? 'dismissible' : ''}`} role="alert">
      <div className="error-content">
        <svg className="error-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="12" cy="12" r="10" />
          <line x1="15" y1="9" x2="9" y2="15" />
          <line x1="9" y1="9" x2="15" y2="15" />
        </svg>
        <div className="error-text">
          <strong>{title}</strong>
          <p>{message}</p>
        </div>
      </div>
      {dismissible && onDismiss && (
        <button type="button" className="error-dismiss" onClick={onDismiss} aria-label="Dismiss">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      )}
    </div>
  )
}