
interface GitProps {
  readonly githubOwner: string
  readonly githubRepo: string
  readonly gitBranch: string
  readonly githubConnectionArn: string
  readonly githubSecretName: string
}

interface StageProps {
  readonly environmentMode: string
  readonly environmentId: string
  readonly databaseUserName: string
  readonly databaseName: string
  readonly logLevel: string
  readonly sentryDsn: string
}

export class Config {
  readonly dataLayerStackName: string
  readonly networkLayerStackName: string
  readonly platformStackName: string

  constructor(public readonly stageProps: StageProps, public readonly gitProps?: GitProps) {
    this.dataLayerStackName = `tgr-${stageProps.environmentMode}-${stageProps.environmentId}-datalayer`
    this.networkLayerStackName = `tgr-${stageProps.environmentMode}-${stageProps.environmentId}-networking`
    this.platformStackName = `tgr-${stageProps.environmentMode}-${stageProps.environmentId}-platform`
  }
  static getConfig(stage: string) {
    if ({}.hasOwnProperty.call(cicdConfigurations, stage)) {
      return cicdConfigurations[stage]
    } else {
      return testStackConfiguration
    }
  }
  static getCicdStageNames() {
    return Object.keys(cicdConfigurations)
  }
}

// Config used when `sst {action} --stage {development stack stage name}`
const testStackConfiguration = new Config({
  environmentMode: "dev",
  environmentId: "1",
  databaseName: "horangi",
  databaseUserName: "storyfier",
  logLevel: "DEBUG",
  sentryDsn: "",
});

// Config used when `sst {action} --stage {cicd pipeline stage name}`
const cicdConfigurations: Readonly<Record<string, Config>> = {
  dev: new Config ({
      environmentMode: "dev",
      environmentId: "1",
      databaseName: "horangi",
      databaseUserName: "storyfier",
      logLevel: "DEBUG",
      sentryDsn: "",
  }, {
      githubOwner: "horangi-ir",
      githubRepo: "tgr-warden-outbound",
      gitBranch: "feat/add_tags",
      githubConnectionArn: "arn:aws:codestar-connections:ap-southeast-1:410801124909:connection/a6f85a35-6448-48ba-ad25-46bc9bb8caeb",
      githubSecretName: "tgr-dev-1-platform-github-ssh",
    }
  ),
  stage: new Config({
      environmentMode: "stage",
      environmentId: "1",
      databaseName: "horangi",
      databaseUserName: "storyfier",
      logLevel: "DEBUG",
      sentryDsn: "",
    }, {
      githubOwner: "horangi-ir",
      githubRepo: "tgr-warden-outbound",
      gitBranch: "release/candidate",
      githubConnectionArn: "arn:aws:codestar-connections:ap-southeast-1:886561456280:connection/5e2e25c3-a871-4b1c-8c78-fe9ae15d43f3",
      githubSecretName: "tgr-stage-1-platform-github-ssh",
    }
  ),
  prod: new Config({
      environmentMode: "prod",
      environmentId: "0",
      databaseName: "horangi",
      databaseUserName: "storyfier",
      logLevel: "DEBUG",
      sentryDsn: "",
    }, {
      githubOwner: "horangi-ir",
      githubRepo: "tgr-warden-outbound",
      gitBranch: "master",
      githubConnectionArn: "arn:aws:codestar-connections:ap-southeast-1:396286753434:connection/375400a4-9f44-495d-aade-35e55f1a3054",
      githubSecretName: "tgr-prod-0-platform-github-ssh",
    }
  )
}
