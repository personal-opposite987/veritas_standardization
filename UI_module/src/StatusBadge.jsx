export default function StatusBadge({ status }) {

  let color = "#6b7280";

  if(status === "Normal") color = "#22c55e";
  if(status === "Out of Range") color = "#ef4444";
  if(status === "High") color = "#f97316";
  if(status === "Low") color = "#eab308";

  return (
    <span
      style={{
        background: color,
        color: "white",
        padding: "5px 10px",
        borderRadius: "20px"
      }}
    >
      {status}
    </span>
  );
}