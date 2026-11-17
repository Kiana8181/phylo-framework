import Link from "next/link";
import { ShieldCheck } from "lucide-react";
import {
  ContactLink,
  LegalDocument,
  LegalTable,
  type LegalSection,
} from "@/components/legal/LegalDocument";
import { LEGAL } from "@/lib/legal";

const USER_DATA_POLICY_URL = "https://developers.google.com/terms/api-services-user-data-policy";
const GOOGLE_CONNECTIONS_URL = "https://myaccount.google.com/permissions";

const HIGHLIGHTS = [
  "With Google sign-in, we store only your email address. Your name, picture and Google tokens are not kept.",
  "We do not sell your data, show ads, use analytics or tracking tools, or train AI models on your data.",
  `Run results are deleted ${LEGAL.resultRetentionDays} days after a run ends. Datasets are deleted ${LEGAL.datasetRetentionDays} days after upload unless you renew them (you are warned ${LEGAL.datasetWarningHours} hours before, and that warning period is configurable).`,
  "You can ask us to delete your account and all of its data at any time.",
];

const SECTIONS: LegalSection[] = [
  {
    id: "who-we-are",
    title: "Who we are",
    body: (
      <>
        <p>
          {LEGAL.appName} is a web application for reconstructing B-cell lineage trees with the Dowser, GCtree, BrepPhylo and ClonalTree
          methods. This service is operated by {LEGAL.operator}, who is responsible for the
          personal data described in this policy. In this policy, “we” and “us” mean the operator.
        </p>
        <p>
          This policy covers the service hosted on this website. {LEGAL.appName} is also open-source
          software: anyone who runs their own copy is responsible for the data in that copy.
        </p>
      </>
    ),
  },
  {
    id: "google-data",
    title: "Google user data",
    body: (
      <>
        <p>
          You can sign in with Google. If you do, we ask Google only for the basic{" "}
          <strong>openid</strong>, <strong>email</strong> and <strong>profile</strong> permissions.
          We cannot see your Gmail, Drive, Contacts, Calendar or any other Google content.
        </p>
        <LegalTable
          caption="What Phylo Framework receives from Google and what happens to it"
          columns={["What we receive", "What we do with it", "Stored?"]}
          rows={[
            [
              "Email address",
              "Identifies your account, creates your username from the part before the @, and is where we send account and run emails.",
              "Yes, until your account is deleted",
            ],
            [
              "Whether Google has verified the address",
              "Checked at sign-in. We record the time your address was confirmed.",
              "Only that time",
            ],
            ["Name and profile picture", "Received as part of the profile response and not used.", "No"],
            ["Google account ID", "Received as part of the profile response and not used.", "No"],
            [
              "Google tokens",
              "The access token is used once at sign-in to read the details above. It and any other token Google issues are then discarded, so we cannot access your Google account afterwards.",
              "No",
            ],
          ]}
        />
        <h3>Limited Use</h3>
        <p>
          Our use of information received from Google APIs adheres to the{" "}
          <a href={USER_DATA_POLICY_URL} target="_blank" rel="noopener noreferrer">
            Google API Services User Data Policy
          </a>
          , including its Limited Use requirements. We use Google user data only to sign you in and
          to run your account. We do not:
        </p>
        <ul>
          <li>sell it or transfer it to advertising platforms, data brokers or information resellers;</li>
          <li>use it for advertising of any kind, including personalized, retargeted or interest-based ads;</li>
          <li>use it to determine creditworthiness or for lending;</li>
          <li>use it to develop, improve or train artificial-intelligence or machine-learning models.</li>
        </ul>
        <h3>Disconnecting Google</h3>
        <p>
          You can remove our access at any time in your{" "}
          <a href={GOOGLE_CONNECTIONS_URL} target="_blank" rel="noopener noreferrer">
            Google Account connections
          </a>
          . This does not delete your {LEGAL.appName} account; to delete it, see{" "}
          <a href="#your-choices">Your choices and rights</a>.
        </p>
      </>
    ),
  },
  {
    id: "data-we-collect",
    title: "Data we collect and how long we keep it",
    body: (
      <>
        <p>We collect only what the service needs to work and to stay secure.</p>
        <LegalTable
          caption="Data collected by Phylo Framework, why, and for how long"
          columns={["Data", "Why", "How long"]}
          rows={[
            [
              "Account: email address, username, a hash of your password (password accounts only), confirmation and creation times",
              "To create your account and sign you in",
              "Until your account is deleted",
            ],
            [
              "Datasets: the files you upload, with their names, sizes and checksums",
              "To run the methods you choose",
              `Until you delete them, or ${LEGAL.datasetRetentionDays} days after upload or the last renewal. You are warned ${LEGAL.datasetWarningHours} hours before automatic deletion and can renew the dataset for another full period. A deleted file is removed from storage; its name, size and checksum stay in your run history until your account is deleted`,
            ],
            [
              "Unfinished uploads",
              "To complete an upload that is in progress",
              "Removed about 24 hours after being abandoned",
            ],
            [
              "Run history: method, parameters, dataset name, status, messages and times",
              "To show your history and make runs reproducible",
              "Until your account is deleted",
            ],
            [
              "Run results: trees, result files and logs",
              "To show you and let you download results",
              `${LEGAL.resultRetentionDays} days after the run ends. The expiry date is shown with the run`,
            ],
            [
              "Email records: recipient and delivery status of run notifications",
              "To deliver each notification once",
              "Removed with the results of that run",
            ],
            [
              "Sign-in protection: counters tied to a keyed hash of your IP address or email address",
              "To limit abuse of the sign-in forms",
              "Removed after the limit's time window, at most about an hour",
            ],
            [
              "Server logs: IP address, requested address, time, and the recipient of each email sent",
              "To keep the service secure and fix faults",
              "Overwritten as new entries are written; not kept for a fixed period",
            ],
          ]}
        />
        <p>
          <strong>Your datasets are yours.</strong> We process them only to run the methods you ask
          for. Sequence data from people can be sensitive, so please read what the{" "}
          <Link href="/terms#your-data">Terms of Service</Link> ask of you before uploading it.
        </p>
      </>
    ),
  },
  {
    id: "how-we-use",
    title: "How we use data",
    body: (
      <>
        <p>We use the data above only to:</p>
        <ul>
          <li>create your account, sign you in and keep your account secure;</li>
          <li>store your datasets, run the methods you start and show you the results;</li>
          <li>apply fair-use limits, such as run quotas and storage limits;</li>
          <li>diagnose faults and protect the service against abuse.</li>
        </ul>
        <p>
          We send email only about your account and your runs: address confirmation, password reset,
          account notices, and a message when a run finishes, fails or expires. We send no marketing
          email.
        </p>
      </>
    ),
  },
  {
    id: "sharing",
    title: "How we share data",
    body: (
      <>
        <p>
          <strong>We do not sell your data</strong>, and we do not share it for anyone else’s
          advertising or marketing. Other users cannot see your datasets, runs or results. Data
          reaches others only in these cases:
        </p>
        <ul>
          <li>
            <strong>Administrators</strong> of this service can open any run and its results in the
            application, and the operator has technical access to the server’s stored files. They
            use this access only when needed to operate the service or to help you.
          </li>
          <li>
            <strong>Infrastructure providers</strong> that run the server and the mail server handle
            data only to provide those services. The mail server sees the email address, subject and
            text of each email we send you.
          </li>
          <li>
            <strong>Google</strong> takes part in sign-in if you choose to use it. Google’s own
            privacy policy applies to your Google account.
          </li>
          <li>
            <strong>Legal requirements:</strong> we may disclose data when the law requires it, or
            when needed to protect the rights and safety of users and the service.
          </li>
        </ul>
        <p>
          The methods run in separate containers on our own server, so running a method does not
          send your dataset to their authors or to any outside service.
        </p>
      </>
    ),
  },
  {
    id: "security",
    title: "How we protect data",
    body: (
      <>
        <ul>
          <li>Connections between your browser and the service are encrypted with HTTPS.</li>
          <li>
            The database and file storage are not reachable from the internet. All access goes
            through the application, which checks that you own what you ask for.
          </li>
          <li>
            Passwords are stored only as salted hashes, and emailed reset and confirmation links
            only as cryptographic hashes.
          </li>
          <li>Sign-in forms are protected by rate limits and a self-hosted proof-of-work check.</li>
        </ul>
        <p>
          No system is perfectly secure. If a breach affects your personal data, we will notify you
          as the law requires. Please keep your password private and download anything you cannot
          afford to lose: the service does not guarantee backups.
        </p>
      </>
    ),
  },
  {
    id: "browser-storage",
    title: "Cookies and browser storage",
    body: (
      <p>
        We do not use cookies, analytics, advertising or third-party tracking tools. Your browser’s
        local storage keeps your sign-in session, basic account details and your display preferences
        (theme, collapsed sidebar). Session storage briefly keeps the security value for a Google
        sign-in and a few values passed between pages. Signing out removes the session and account
        details from your browser.
      </p>
    ),
  },
  {
    id: "your-choices",
    title: "Your choices and rights",
    body: (
      <>
        <ul>
          <li>
            <strong>Delete a dataset</strong> yourself from your dashboard, unless a run in progress
            is still using it.
          </li>
          <li>
            <strong>Download</strong> your run results from the application while they are kept.
          </li>
          <li>
            <strong>Delete your account:</strong> email <ContactLink /> from your account’s address.
            We will delete your account, datasets, runs, results and email records, and confirm when
            it is done, within {LEGAL.requestResponseDays} days.
          </li>
          <li>
            <strong>Access or correct your data, object to its use or ask for a copy, including of your datasets:</strong> email
            the same address. We reply within {LEGAL.requestResponseDays} days.
          </li>
        </ul>
        <p>
          After an account is deleted, entries in server logs are overwritten over time, and any copy
          in a manual backup is removed when that backup is. Depending on where you live, you may also
          have the right to complain to your data protection authority.
        </p>
      </>
    ),
  },
  {
    id: "transfers-children",
    title: "International users and children",
    body: (
      <p>
        Your data is stored on the server that hosts this service, which may be in a different
        country from yours. The service is meant for researchers and is not directed at anyone under
        16. If you believe a child has given us personal data, contact us and we will delete it.
      </p>
    ),
  },
  {
    id: "changes",
    title: "Changes to this policy",
    body: (
      <p>
        If we change this policy, we will publish the new version here and update its effective date.
        If a change affects how we use data we already hold, including Google user data, we will tell
        you first and ask for your consent where it is required.
      </p>
    ),
  },
  {
    id: "contact",
    title: "Contact",
    body: (
      <p>
        Questions or requests about your privacy: {LEGAL.operator}, <ContactLink />.
      </p>
    ),
  },
];

export function PrivacyDoc() {
  return (
    <LegalDocument
      active="privacy"
      icon={ShieldCheck}
      title="Privacy Policy"
      summary={`What ${LEGAL.appName} collects, including data from Google sign-in, how it is used and protected, and how to have it deleted.`}
      highlights={HIGHLIGHTS}
      sections={SECTIONS}
    />
  );
}
