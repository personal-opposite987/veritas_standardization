import { BrowserRouter, Routes, Route } from "react-router-dom";

import Dashboard from "./Dashboard";
import Encounters from "./Encounters";
import EncounterDetail from "./EncounterDetail";
import Errors from "./Errors";

function App() {
  return (
    <BrowserRouter>

      <Routes>

        <Route
          path="/"
          element={<Dashboard />}
        />

        <Route
          path="/encounters"
          element={<Encounters />}
        />

        <Route
          path="/encounters/:id"
          element={<EncounterDetail />}
        />

        <Route
          path="/errors"
          element={<Errors />}
        />

      </Routes>

    </BrowserRouter>
  );
}

export default App;