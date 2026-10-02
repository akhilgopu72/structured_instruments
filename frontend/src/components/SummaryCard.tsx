interface SummaryCardProps {
  label: string;
  value: string;
  accent?: 'blue' | 'green' | 'red' | 'yellow';
  onClick?: () => void;
  active?: boolean;
}

const accentColors = {
  blue: 'border-blue-500 text-blue-400',
  green: 'border-green-500 text-green-400',
  red: 'border-red-500 text-red-400',
  yellow: 'border-yellow-500 text-yellow-400',
};

const activeRing = {
  blue: 'ring-2 ring-blue-500',
  green: 'ring-2 ring-green-500',
  red: 'ring-2 ring-red-500',
  yellow: 'ring-2 ring-yellow-500',
};

export default function SummaryCard({ label, value, accent = 'blue', onClick, active = false }: SummaryCardProps) {
  const interactive = onClick != null;
  const className = [
    'bg-gray-800 rounded-lg p-5 border-l-4 text-left w-full transition-colors',
    accentColors[accent],
    interactive ? 'cursor-pointer hover:bg-gray-750' : '',
    active ? activeRing[accent] : '',
  ]
    .filter(Boolean)
    .join(' ');

  if (interactive) {
    return (
      <button type="button" onClick={onClick} className={className}>
        <p className="text-gray-400 text-sm font-medium">{label}</p>
        <p className="text-2xl font-bold text-white mt-1">{value}</p>
      </button>
    );
  }

  return (
    <div className={className}>
      <p className="text-gray-400 text-sm font-medium">{label}</p>
      <p className="text-2xl font-bold text-white mt-1">{value}</p>
    </div>
  );
}
