import { useEffect, useState } from "react";
import api from "./services/api";
import { Link } from "react-router-dom";
import StatusBadge from "./StatusBadge";

export default function Encounters() {

  const [rows, setRows] = useState([]);
  const [search, setSearch] = useState("");

 useEffect(() => {

  api.get(`/encounters?search=${search}`)
    .then(res => setRows(res.data.results));

}, [search]);

  return (
    <div className="container">

      <h1>Encounters</h1>

      <input
  type="text"
  placeholder="Search diagnosis..."
  value={search}
  onChange={(e)=>setSearch(e.target.value)}
  style={{
    padding:"10px",
    width:"300px",
    marginBottom:"20px"
  }}
/>

      <table>

        <thead>
          <tr>
            <th>ID</th>
            <th>Diagnosis</th>
            <th>Admission</th>
            <th>Status</th>
          </tr>
        </thead>

        <tbody>

          {rows.map(row => (
            <tr key={row.encounter_id}>
              <td>
  <Link to={`/encounters/${row.encounter_id}`}>
    {row.encounter_id.slice(0,8)}
  </Link>
</td>
              <td>{row.diagnosis}</td>
              <td>{row.admission_date_raw}</td>
              <td>
  <StatusBadge
    status={row.date_validation_status}
  />
</td>
            </tr>
          ))}

        </tbody>

      </table>

    </div>
  );
}