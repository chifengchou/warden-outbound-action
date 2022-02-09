import { Template } from "aws-cdk-lib/assertions";
import * as sst from "@serverless-stack/resources";
import OutboundStack from "../stacks/outboundStack";

test("Test Stack", () => {
  const app = new sst.App();
  app.setDefaultFunctionProps({
    runtime: "python3.8"
  });
  // WHEN
  const stack = new OutboundStack(app, "test-stack");
  // THEN
  const template = Template.fromStack(stack);
  template.resourceCountIs("AWS::Lambda::Function", 1);
});
