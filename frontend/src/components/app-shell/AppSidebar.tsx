import type { ReactNode } from 'react'
import { FileText, LayoutGrid, LogOut, PanelLeftClose, PanelLeftOpen, Settings, User, Users } from 'lucide-react'

import { displayNameFromEmail, useAuthSession } from '../../lib/authSession'
import { ClientAvatar } from './ui'

export type ShellSection = 'home' | 'clients' | 'documents' | 'settings'

const NAV: { id: ShellSection; label: string; icon: ReactNode }[] = [
  { id: 'home', label: '대시보드', icon: <LayoutGrid className="h-[18px] w-[18px]" /> },
  { id: 'clients', label: '내담자 관리', icon: <Users className="h-[18px] w-[18px]" /> },
  { id: 'documents', label: '문서 보관함', icon: <FileText className="h-[18px] w-[18px]" /> },
]

/** Figma 사이드바: 로고, 대시보드/내담자 관리/문서 보관함, 하단 설정 + 상담사 프로필. */
export default function AppSidebar({
  active,
  collapsed,
  onNavigate,
  onToggleCollapsed,
}: {
  active: ShellSection
  collapsed: boolean
  onNavigate: (section: ShellSection) => void
  onToggleCollapsed: () => void
}) {
  const { email, signOut, signingOut } = useAuthSession()

  return (
    <aside
      className={`desktop-sidebar border-grey-200 bg-white transition-[width] duration-200 md:fixed md:inset-y-0 md:left-0 md:z-40 md:border-r ${
        collapsed ? 'md:w-[64px]' : 'md:w-[253px]'
      }`}
    >
      <div className="flex h-full flex-col">
        <div className={`flex h-[73px] items-center border-b border-grey-200 ${collapsed ? 'justify-center px-2' : 'justify-between px-6'}`}>
          {!collapsed && <img src="/remind-logo.png" alt="Re:mind" className="h-7 w-auto object-contain" />}
          <button
            type="button"
            onClick={onToggleCollapsed}
            className="inline-flex h-8 w-8 items-center justify-center rounded-md text-grey-500 hover:bg-grey-100 hover:text-grey-900"
            aria-label={collapsed ? '사이드바 열기' : '사이드바 닫기'}
            title={collapsed ? '사이드바 열기' : '사이드바 닫기'}
          >
            {collapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
          </button>
        </div>

        <nav aria-label="주 메뉴" className={`flex flex-col gap-2 ${collapsed ? 'items-center px-2 py-4' : 'px-3 py-6'}`}>
          {NAV.map((item) => (
            <SidebarItem key={item.id} active={active === item.id} collapsed={collapsed} icon={item.icon} label={item.label} onClick={() => onNavigate(item.id)} />
          ))}
        </nav>

        <div className={`mt-auto flex flex-col gap-2 border-t border-grey-200 ${collapsed ? 'items-center px-2 py-4' : 'px-3 py-4'}`}>
          <SidebarItem active={active === 'settings'} collapsed={collapsed} icon={<Settings className="h-[18px] w-[18px]" />} label="설정" onClick={() => onNavigate('settings')} />
        </div>

        <div className={`border-t border-grey-200 ${collapsed ? 'flex justify-center px-2 py-4' : 'px-6 py-5'}`}>
          {collapsed ? (
            <button type="button" onClick={() => onNavigate('settings')} aria-label="계정" className="rounded-full">
              <ClientAvatar size={36} />
            </button>
          ) : (
            <div className="flex items-center gap-3">
              <ClientAvatar size={40} />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-bold text-grey-900">{displayNameFromEmail(email)}</p>
                <p className="truncate text-xs text-grey-500" title={email || ''}>{email || '상담사'}</p>
              </div>
              <button
                type="button"
                onClick={() => void signOut()}
                disabled={signingOut}
                aria-label="로그아웃"
                title="로그아웃"
                className="inline-flex h-8 w-8 items-center justify-center rounded-md text-grey-500 hover:bg-grey-100 hover:text-grey-900 disabled:opacity-50"
              >
                <LogOut className="h-4 w-4" />
              </button>
            </div>
          )}
        </div>
      </div>
    </aside>
  )
}

function SidebarItem({ active, collapsed, icon, label, onClick }: { active: boolean; collapsed: boolean; icon: ReactNode; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-current={active ? 'page' : undefined}
      title={label}
      className={`flex h-12 items-center gap-3 rounded-[10px] text-sm font-semibold transition ${collapsed ? 'w-10 justify-center' : 'w-full px-4'} ${
        active ? 'bg-primary-50 text-grey-900' : 'text-grey-500 hover:bg-grey-100 hover:text-grey-900'
      }`}
    >
      <span className={active ? 'text-grey-900' : 'text-grey-500'}>{icon}</span>
      {!collapsed && <span>{label}</span>}
    </button>
  )
}

/** 모바일 상단 내비게이션(details) 안에서 쓰는 단순 버튼 목록 */
export function MobileNavItems({ onNavigate }: { onNavigate: (section: ShellSection) => void }) {
  const { email, signOut } = useAuthSession()
  return (
    <>
      {NAV.map((item) => (
        <button key={item.id} type="button" onClick={() => onNavigate(item.id)} className="flex h-10 items-center gap-2 rounded-[8px] px-3 text-left text-sm font-semibold text-grey-800 hover:bg-grey-100">
          {item.icon}{item.label}
        </button>
      ))}
      <button type="button" onClick={() => onNavigate('settings')} className="flex h-10 items-center gap-2 rounded-[8px] px-3 text-left text-sm font-semibold text-grey-800 hover:bg-grey-100">
        <Settings className="h-[18px] w-[18px]" />설정
      </button>
      <div className="flex items-center justify-between gap-2 border-t border-grey-200 pt-3 text-xs text-grey-500">
        <span className="flex min-w-0 items-center gap-1.5"><User className="h-3.5 w-3.5 shrink-0" /><span className="truncate">{email || '상담사'}</span></span>
        <button type="button" onClick={() => void signOut()} className="inline-flex items-center gap-1 font-bold text-grey-700"><LogOut className="h-3.5 w-3.5" />로그아웃</button>
      </div>
    </>
  )
}
