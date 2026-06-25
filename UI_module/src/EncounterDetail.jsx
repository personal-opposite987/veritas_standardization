import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import api from "./services/api";

export default function EncounterDetail() {
  const { id } = useParams();

  const [data, setData] = useState(null);

  useEffect(() => {
    api.get(`/encounters/${id}`)
      .then(res => setData(res.data))
      .catch(console.error);
  }, [id]);

  if (!data) return <h2>Loading...</h2>;

  return (
    <div className="container">
      <h1>Encounter Details</h1>

      <h3>Diagnosis</h3>
      <p>{data.encounter.diagnosis}</p>

      <h3>Hospital</h3>
      <p>{data.encounter.hospital_name}</p>

      <h3>Doctor</h3>
      <p>{data.encounter.doctor_name}</p>

      <h2>Lab Results</h2>

      <table>
        <thead>
          <tr>
            <th>Test</th>
            <th>Result</th>
            <th>Status</th>
          </tr>
        </thead>

        <tbody>
          {data.lab_results.map(r => (
            <tr key={r.result_id}>
              <td>{r.test_name_raw}</td>
              <td>{r.result_raw}</td>
              <td>{r.validation_status}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Medications</h2>

      <ul>
        {data.medications.map(m => (
          <li key={m.medication_id}>
            {m.medicine_raw}
          </li>
        ))}
      </ul>

    </div>
  );
}