import { FileText, Quote, Star } from 'lucide-react'

interface LandingPageProps { onLogin: () => void; onSignup: () => void }

export default function LandingPage({ onLogin, onSignup }: LandingPageProps) {
  return (
    <main className="landing bg-white text-slate-950">
      <header className="landing-header">
        <img src="/remind-logo.png" alt="Re:mind" />
        <div className="flex items-center gap-3">
          <button type="button" onClick={onLogin} className="px-3 py-2 font-semibold text-slate-500 hover:text-slate-900">로그인</button>
          <button type="button" onClick={onSignup} className="rounded-md border border-slate-300 px-3 py-2 font-semibold text-slate-700 hover:bg-slate-50">무료로 시작하기</button>
        </div>
      </header>
      <section className="landing-hero">
        <div className="hero-layout">
          <h1 className="hero-headline">심리상담사의 상담 이후<br />기록·문서화 업무를 돕는 AI 서비스,</h1>
          <div className="hero-copy">
            <img src="/remind-logo.png" alt="Re:mind" className="hero-logo" />
            <p className="hero-description">상담사의 기록 시간을 줄이고 문서의 완성도는 높여 상담에 더 집중할 수 있도록 돕습니다</p>
            <button type="button" onClick={onSignup} className="hero-cta bg-blue-600 font-extrabold text-white hover:bg-blue-700">무료로 시작하기</button>
          </div>
          <div className="mockup-frame">
          <div className="product-mockup" aria-label="회기 요약과 AI 검토 예시">
            <article className="mockup-card summary-card">
              <div className="mockup-heading"><FileText className="text-blue-600" /><h2>회기 요약 초안</h2><span className="mockup-label">초안 생성됨</span></div>
              <p className="mt-2 text-xs font-semibold text-slate-400">CASE-204 · 5회기 · 2026.04.28</p>
              <SummaryLine title="주요 호소" badge="STT 근거 3개" text="진로·취업 준비 과정에서 불안과 압박감을 호소함." />
              <SummaryLine title="상담자 개입" badge="메모 기반" text="감정 명료화와 현실 검증 질문으로 불안을 구체화함." />
              <SummaryLine title="내담자 반응" badge="원문 근거 있음" text="또래 비교 이후 자기비난과 자신감 저하를 보고함." />
              <div className="summary-badges">
                {['가명 / 케이스 ID', '상담사 수정 확정', '최종 문서화'].map((label, index) => (
                  <span key={label} className={`summary-badge ${index === 1 ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-blue-100 bg-blue-50 text-blue-600'}`}>
                    <span aria-hidden="true" className="h-1.5 w-1.5 shrink-0 rounded-full bg-current" />{label}
                  </span>
                ))}
              </div>
            </article>
            <div className="mockup-support">
            <article className="mockup-card review-card">
              <div className="mockup-heading text-blue-700"><Star /><h2>AI 검토 완료</h2></div>
              <ReviewRow label="수정 필요" value="3개" color="text-red-500" />
              <ReviewRow label="누락 가능 항목" value="2개" color="text-orange-500" />
              <ReviewRow label="상담사 확인 필요" value="1개" color="text-blue-600" />
            </article>
            <article className="mockup-card evidence-card">
              <div className="mockup-heading text-emerald-600"><Quote /><h2>원문 근거 보기</h2></div>
              <EvidenceRow label="STT" text="제가 뒤처지는 것 같아요." />
              <EvidenceRow label="상담사 메모" text="취업 불안, 자기비난 반복" />
            </article>
            </div>
          </div>
          </div>
        </div>
      </section>
    </main>
  )
}

function SummaryLine({ badge, text, title }: { badge: string; text: string; title: string }) {
  return <div className="summary-line"><div className="mockup-heading text-blue-600"><h3>{title}</h3><span className="mockup-label">{badge}</span></div><p>{text}</p></div>
}
function ReviewRow({ color, label, value }: { color: string; label: string; value: string }) {
  return <div className="review-row"><span className="text-slate-500">{label}</span><span className={color}>{value}</span></div>
}
function EvidenceRow({ label, text }: { label: string; text: string }) {
  return <div className="mt-4"><span className="mockup-label">{label}</span><p className="mt-2 font-semibold italic text-slate-600">"{text}"</p></div>
}
