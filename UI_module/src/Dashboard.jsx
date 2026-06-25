import { useEffect, useState } from "react";
import api from "./services/api";
import ValidationChart from "./ValidationChart";

export default function Dashboard() {

  const [stats, setStats] = useState(null);
  const [validation, setValidation] = useState([]);

  useEffect(() => {

    api.get("/stats/summary")
      .then(res => setStats(res.data));

    api.get("/stats/validation-breakdown")
      .then(res => setValidation(res.data));

  }, []);

  if (!stats) return <h2>Loading...</h2>;

  return (
    <div className="container">

      <h1>Veritas Clinical Dashboard</h1>

      <a href="/encounters">
      View Encounters
      </a>

      <div className="cards">

        <div className="card">
          <h3>Encounters</h3>
          <h2>{stats.encounters_total}</h2>
        </div>

        <div className="card">
          <h3>Lab Results</h3>
          <h2>{stats.lab_results_total}</h2>
        </div>

        <div className="card">
          <h3>Medications</h3>
          <h2>{stats.medications_total}</h2>
        </div>

        <div className="card">
          <h3>Duplicates</h3>
          <h2>{stats.duplicates_total}</h2>
        </div>

      </div>

      <h2 style={{ marginTop: "40px" }}>
        Validation Breakdown
      </h2>

      <ValidationChart data={validation} />
    </div>
  );
}