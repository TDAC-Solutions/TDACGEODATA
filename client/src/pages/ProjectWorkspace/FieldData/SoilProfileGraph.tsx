import type { BoreholeRecord } from "../../../api/fieldData";

interface SoilProfileGraphProps {
  records: BoreholeRecord[];
}

/*
 * Borehole / Soil Profile graph. Moved unchanged from BoreholeModule into
 * Field Data -> Overview; records are expected sorted by depth_from.
 */
export function SoilProfileGraph({ records }: SoilProfileGraphProps) {
  if (records.length === 0) {
    return (
      <div className="empty-state">
        <h3>No borehole/drilling data</h3>
        <p>No borehole/drilling data available for this location.</p>
      </div>
    );
  }

  /*
   * Calculate total borehole depth from the actual records.
   */
  const maxDepth = Math.max(
    ...records.map(
      (record) =>
        record.depth_to ?? record.depth_from
    ),
    1
  );

  /*
   * Select a sensible depth scale.
   */
  const depthStep =
    maxDepth <= 20
      ? 2
      : maxDepth <= 50
        ? 5
        : 10;

  const depthTicks = Array.from(
    {
      length:
        Math.floor(maxDepth / depthStep) + 1,
    },
    (_, index) => index * depthStep
  );

  if (
    depthTicks[depthTicks.length - 1] <
    maxDepth
  ) {
    depthTicks.push(maxDepth);
  }

  return (
    <>
          {/* BOREHOLE / SOIL PROFILE */}
          <div className="borehole-profile-panel">
            <div className="borehole-profile-header">
              <div>
                <h3 className="panel-subtitle">
                  Borehole / Soil Profile
                </h3>

                <p className="page-sub">
                  Stratigraphic profile based on
                  borehole records
                </p>
              </div>

              <div className="profile-depth-summary">
                <span>Total depth</span>
                <strong>
                  {maxDepth.toFixed(2)} m
                </strong>
              </div>
            </div>

            <div className="borehole-profile-chart">
              {/* DEPTH SCALE */}
              <div className="profile-scale">
                <div className="profile-scale-title">
                  Depth
                  <span>(m)</span>
                </div>

                {depthTicks.map((depth) => (
                  <div
                    key={depth}
                    className="profile-scale-tick"
                    style={{
                      top: `${
                        (depth / maxDepth) *
                        100
                      }%`,
                    }}
                  >
                    <span>{depth}</span>
                    <i />
                  </div>
                ))}
              </div>

              {/* STRATIGRAPHIC LAYERS */}
              <div className="profile-strata">
                {records.map(
                  (record, index) => {
                    const from =
                      record.depth_from;

                    const to =
                      record.depth_to ??
                      record.depth_from;

                    const thickness = Math.max(
                      to - from,
                      0.05
                    );

                    return (
                      <div
                        key={`${record.depth_from}-${record.depth_to}-${index}`}
                        className={`profile-layer profile-layer-${
                          index % 6
                        }`}
                        style={{
                          top: `${
                            (from /
                              maxDepth) *
                            100
                          }%`,
                          height: `${Math.max(
                            (thickness /
                              maxDepth) *
                              100,
                            1
                          )}%`,
                        }}
                      >
                        <div className="profile-layer-content">
                          <div className="profile-layer-depth">
                            {from.toFixed(2)}
                            {" – "}
                            {to.toFixed(2)} m
                          </div>

                          <strong>
                            {record.soil_description ||
                              "Unclassified material"}
                          </strong>

                          {record.sand_clay && (
                            <span className="profile-material">
                              {
                                record.sand_clay
                              }
                            </span>
                          )}
                        </div>
                      </div>
                    );
                  }
                )}
              </div>
            </div>
          </div>
    </>
  );
}
