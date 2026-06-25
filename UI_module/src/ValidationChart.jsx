import { PieChart, Pie, Tooltip, Cell } from "recharts";

const COLORS = [
  "#22c55e",
  "#ef4444",
  "#3b82f6",
  "#eab308",
  "#f97316",
  "#6b7280",
];

export default function ValidationChart({ data }) {
  return (
    <PieChart width={500} height={350}>
      <Pie
        data={data}
        dataKey="count"
        nameKey="validation_status"
        outerRadius={120}
        label
      >
        {data.map((_, index) => (
          <Cell
            key={index}
            fill={COLORS[index % COLORS.length]}
          />
        ))}
      </Pie>

      <Tooltip />
    </PieChart>
  );
}