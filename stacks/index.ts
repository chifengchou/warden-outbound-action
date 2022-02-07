import OutboundStack from "./OutboundStack";
import * as sst from "@serverless-stack/resources";

export default function main(app: sst.App): void {
  // Set default runtime for all functions
  app.setDefaultFunctionProps({
    runtime: "python3.8"
  });

  new OutboundStack(app, "outbound-stack");

  // Add more stacks
}
