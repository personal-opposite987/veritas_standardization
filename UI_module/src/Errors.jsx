import { useEffect, useState } from "react";
import api from "./services/api";

export default function Errors() {

  const [errors,setErrors] = useState([]);

  useEffect(() => {

    api.get("/errors")
      .then(res => setErrors(res.data));

  }, []);

  return (
    <div className="container">

      <h1>Error Log</h1>

      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>Source</th>
            <th>Reason</th>
          </tr>
        </thead>

        <tbody>

          {errors.map(e => (
            <tr key={e.error_id}>
              <td>{e.error_id}</td>
              <td>{e.source_file}</td>
              <td>{e.error_reason}</td>
            </tr>
          ))}

        </tbody>

      </table>

    </div>
  );
}