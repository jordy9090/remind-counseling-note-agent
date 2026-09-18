// Figma tokens (수연님 대시보드 디자인). hex는 캡처 기준 추정값이며 토큰 확정값이 오면 여기만 바꾼다.
module.exports = {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        primary: {
          50: '#EEF4FF',
          100: '#DCE7FF',
          400: '#2563EB',
          500: '#1D4ED8',
          900: '#1E3A8A',
        },
        grey: {
          100: '#F3F4F6',
          200: '#E5E7EB',
          400: '#9CA3AF',
          500: '#6B7280',
          600: '#4B5563',
          700: '#374151',
          800: '#1F2937',
          900: '#111827',
        },
        danger: { 50: '#FEF2F2', 500: '#EF4444' },
        success: { 50: '#ECFDF5', 500: '#22C55E' },
        // 대시보드 카드 외곽선: primary 21% 불투명도, 1px
        line: 'rgba(37, 99, 235, 0.21)',
      },
      borderRadius: {
        modal: '24px',
        card: '16px',
      },
      boxShadow: {
        card: '0 4px 16px rgba(30, 58, 138, 0.06)',
        modal: '0 24px 60px rgba(17, 24, 39, 0.18)',
      },
    },
  },
  plugins: [],
}
