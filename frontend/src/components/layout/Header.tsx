interface HeaderProps {
  title: string
}

export const Header: React.FC<HeaderProps> = ({ title }) => {
  return (
    <header className="border-b border-gray-200 bg-white shadow-sm">
      <div className="mx-auto max-w-7xl px-6 py-4">
        <h1 className="text-2xl font-bold text-gray-900">{title}</h1>
      </div>
    </header>
  )
}
