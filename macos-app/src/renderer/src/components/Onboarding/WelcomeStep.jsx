export default function WelcomeStep({ onNext }) {
  return (
    <div className="flex flex-col items-center justify-center flex-1 gap-6 animate-fade-slide">
      <span className="text-amber text-6xl leading-none">&#9670;</span>
      <h1 className="text-text text-2xl font-semibold font-ui tracking-wide">
        Welcome to ChanakyaTrade
      </h1>
      <p className="text-muted text-sm font-ui max-w-md text-center leading-relaxed">
        AI-powered trading terminal for Indian markets.
        NSE, BSE, and F&amp;O with real-time data, AI analysis, and automated strategies.
      </p>
      <button
        onClick={onNext}
        className="mt-4 px-8 py-2.5 bg-amber text-black font-ui font-extrabold text-sm rounded-lg
                   hover:brightness-110 transition-all active:scale-95 shadow-sm cursor-pointer"
      >
        Get Started
      </button>
    </div>
  )
}
