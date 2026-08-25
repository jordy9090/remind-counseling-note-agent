import { useEffect, useState } from 'react'
import { FileText, Quote, Star } from 'lucide-react'

interface LandingPageProps {
  onLogin: () => void
  onStart: () => void
}

const BASE_WIDTH = 988
const BASE_HEIGHT = 645
const BASE_HEADER_HEIGHT = 46

function getViewportSize() {
  if (typeof window === 'undefined') {
    return { height: BASE_HEIGHT, width: BASE_WIDTH }
  }

  return { height: window.innerHeight, width: window.innerWidth }
}

export default function LandingPage({ onLogin, onStart }: LandingPageProps) {
  const [viewport, setViewport] = useState(getViewportSize)
  const scale = Math.min(viewport.width / BASE_WIDTH, viewport.height / BASE_HEIGHT)
  const headerHeight = BASE_HEADER_HEIGHT * scale
  const s = (value: number) => value * scale

  useEffect(() => {
    const handleResize = () => setViewport(getViewportSize())

    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  return (
    <main className="h-screen overflow-hidden bg-white text-slate-950">
      <header
        className="flex items-center justify-between border-b border-slate-100 bg-white"
        style={{
          height: headerHeight,
          paddingLeft: s(30),
          paddingRight: s(22),
        }}
      >
        <img
          src="/remind-logo.png"
          alt="Re:mind"
          className="object-contain"
          style={{ height: s(19), width: s(96) }}
        />
        <div className="flex items-center" style={{ gap: s(22) }}>
          <button
            type="button"
            onClick={onLogin}
            className="font-semibold text-slate-500 hover:text-slate-900"
            style={{ fontSize: s(10) }}
          >
            로그인
          </button>
          <button
            type="button"
            onClick={onStart}
            className="rounded-[5px] border border-slate-300 bg-white font-semibold text-slate-700 shadow-sm hover:bg-slate-50"
            style={{
              fontSize: s(11),
              height: s(30),
              paddingLeft: s(14),
              paddingRight: s(14),
            }}
          >
            무료로 시작하기
          </button>
        </div>
      </header>

      <section
        className="relative overflow-hidden bg-[linear-gradient(135deg,#f8fbff_0%,#edf4ff_48%,#dbe8ff_100%)]"
        style={{ height: viewport.height - headerHeight }}
      >
        <div
          className="absolute rounded-full bg-blue-200/35"
          style={{ height: s(94), left: s(420), top: s(274), width: s(94) }}
        />
        <div
          className="absolute rounded-full bg-white/55"
          style={{ height: s(350), right: s(-50), top: s(221), width: s(350) }}
        />
        <div
          className="absolute rounded-full bg-blue-200/30"
          style={{ bottom: s(-95), height: s(190), right: s(33), width: s(190) }}
        />

        <div className="absolute" style={{ height: s(599), left: 0, top: 0, width: s(988) }}>
          <div className="absolute" style={{ left: s(72), top: s(101) }}>
            <h1
              className="whitespace-pre-line font-extrabold tracking-[-0.02em] text-slate-950"
              style={{ fontSize: s(42), lineHeight: 1.24 }}
            >
              {'심리상담사의 상담 이후\n기록·문서화 업무를 돕는 AI 서비스,'}
            </h1>
            <img
              src="/remind-logo.png"
              alt="Re:mind"
              className="object-contain"
              style={{ height: s(56), marginTop: s(20), width: s(282) }}
            />
            <p
              className="whitespace-pre-line font-medium text-slate-600"
              style={{ fontSize: s(19), lineHeight: 1.42, marginTop: s(26) }}
            >
              {'상담사의 기록 시간을 줄이고 문서의 완성도는\n높여 상담에 더 집중할 수 있도록 돕습니다'}
            </p>
            <button
              type="button"
              onClick={onStart}
              className="rounded-[5px] bg-blue-600 font-extrabold text-white shadow-[0_5px_9px_rgba(30,80,180,0.28)] hover:bg-blue-700"
              style={{
                fontSize: s(21),
                height: s(49),
                marginTop: s(34),
                width: s(214),
              }}
            >
              무료로 시작하기
            </button>
          </div>

          <div
            className="absolute border border-slate-200 bg-white shadow-[0_15px_35px_rgba(57,92,143,0.14)]"
            style={{
              borderRadius: s(18),
              height: s(284),
              left: s(494),
              padding: `${s(16)}px ${s(19)}px`,
              top: s(249),
              width: s(306),
            }}
          >
            <div className="flex items-start" style={{ gap: s(9) }}>
              <FileText className="text-blue-600" style={{ height: s(19), marginTop: s(2), width: s(19) }} />
              <div>
                <div className="flex items-center" style={{ gap: s(8) }}>
                  <p className="font-extrabold leading-none text-slate-900" style={{ fontSize: s(18) }}>
                    회기 요약 초안
                  </p>
                  <span
                    className="bg-blue-50 font-extrabold text-blue-600"
                    style={{ borderRadius: s(4), fontSize: s(10), padding: `${s(3)}px ${s(7)}px` }}
                  >
                    초안 생성됨
                  </span>
                </div>
                <p className="font-semibold text-slate-400" style={{ fontSize: s(12), marginTop: s(8) }}>
                  CASE-204 · 5회기 · 2026.04.28
                </p>
              </div>
            </div>

            <SummaryLine scale={scale} title="주요 호소" badge="STT 근거 3개" text="사회적 상황에서 타인의 평가를 예상하며 불안과 회피를 경험함." />
            <SummaryLine scale={scale} title="상담자 개입" badge="메모 기반" text="감정 명료화와 현실 검증 질문으로 불안을 구체화함." />
            <SummaryLine scale={scale} title="내담자 반응" badge="원문 근거 있음" text="또래 비교 이후 자기비난과 자신감 저하를 보고함." />

            <div className="absolute flex" style={{ bottom: s(33), gap: s(7), left: s(19) }}>
              {['가명 / 케이스 ID', '상담사 수정 확정', '최종 문서화'].map((label, index) => (
                <span
                  key={label}
                  className={`inline-flex items-center border font-bold ${
                    index === 1 ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-blue-100 bg-blue-50 text-blue-600'
                  }`}
                  style={{
                    borderRadius: 999,
                    fontSize: s(10),
                    gap: s(5),
                    height: s(24),
                    paddingLeft: s(10),
                    paddingRight: s(10),
                  }}
                >
                  <span
                    className={`rounded-full ${index === 1 ? 'bg-emerald-500' : 'bg-blue-500'}`}
                    style={{ height: s(6), width: s(6) }}
                  />
                  {label}
                </span>
              ))}
            </div>
          </div>

          <div
            className="absolute border border-blue-100 bg-white shadow-[0_12px_24px_rgba(57,92,143,0.12)]"
            style={{
              borderRadius: s(14),
              height: s(108),
              left: s(728),
              padding: `${s(13)}px ${s(14)}px`,
              top: s(226),
              width: s(165),
            }}
          >
            <div className="flex items-center" style={{ gap: s(6) }}>
              <Star className="fill-blue-100 text-blue-600" style={{ height: s(18), width: s(18) }} />
              <p className="font-extrabold text-blue-700" style={{ fontSize: s(14) }}>
                AI 검토 완료
              </p>
            </div>
            <ReviewRow scale={scale} label="수정 필요" value="3개" color="text-red-500" />
            <ReviewRow scale={scale} label="누락 가능 항목" value="2개" color="text-orange-500" />
            <ReviewRow scale={scale} label="상담사 확인 필요" value="1개" color="text-blue-600" />
          </div>

          <div
            className="absolute border border-emerald-200 bg-white shadow-[0_12px_24px_rgba(57,92,143,0.10)]"
            style={{
              borderRadius: s(13),
              height: s(134),
              left: s(746),
              padding: `${s(12)}px ${s(14)}px`,
              top: s(357),
              width: s(184),
            }}
          >
            <div className="flex items-center text-emerald-600" style={{ gap: s(7) }}>
              <Quote style={{ height: s(20), width: s(20) }} />
              <p className="font-extrabold" style={{ fontSize: s(14) }}>
                원문 근거 보기
              </p>
            </div>
            <EvidenceRow scale={scale} label="STT" text="제가 뒤처지는 것 같아요." />
            <EvidenceRow scale={scale} label="상담사 메모" text="취업 불안, 자기비난 반복" />
          </div>
        </div>
      </section>
    </main>
  )
}

function SummaryLine({ badge, scale, text, title }: { badge: string; scale: number; text: string; title: string }) {
  const s = (value: number) => value * scale

  return (
    <div style={{ marginTop: s(17) }}>
      <div className="flex items-center" style={{ gap: s(9) }}>
        <p className="font-extrabold text-blue-600" style={{ fontSize: s(13) }}>
          {title}
        </p>
        <span
          className="bg-blue-50 font-extrabold text-blue-600"
          style={{ borderRadius: s(4), fontSize: s(10), padding: `${s(3)}px ${s(7)}px` }}
        >
          {badge}
        </span>
      </div>
      <p className="truncate font-medium text-slate-700" style={{ fontSize: s(12), marginTop: s(5) }}>
        {text}
      </p>
    </div>
  )
}

function ReviewRow({ color, label, scale, value }: { color: string; label: string; scale: number; value: string }) {
  const s = (item: number) => item * scale

  return (
    <div className="flex items-center justify-between font-semibold" style={{ fontSize: s(12), marginTop: s(6) }}>
      <span className="text-slate-500">{label}</span>
      <span className={color}>{value}</span>
    </div>
  )
}

function EvidenceRow({ label, scale, text }: { label: string; scale: number; text: string }) {
  const s = (value: number) => value * scale

  return (
    <div style={{ marginTop: s(13) }}>
      <span
        className="bg-blue-50 font-extrabold text-blue-600"
        style={{ borderRadius: s(4), fontSize: s(10), padding: `${s(3)}px ${s(7)}px` }}
      >
        {label}
      </span>
      <p className="font-semibold italic text-slate-600" style={{ fontSize: s(12), marginTop: s(7) }}>
        "{text}"
      </p>
    </div>
  )
}
