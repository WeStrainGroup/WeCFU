use serde::Deserialize;
use url::Url;

pub const MAX_LINE: usize = 32 * 1024;

#[derive(Deserialize)]
#[serde(tag = "event", rename_all = "snake_case", deny_unknown_fields)]
pub enum HostEvent {
    Ready {
        url: String,
        session_id: String,
        version: String,
    },
    Error {
        message: String,
        session_id: String,
    },
}

pub fn ready_url(event: HostEvent, session: &str, version: &str) -> Result<Url, String> {
    match event {
        HostEvent::Ready {
            url,
            session_id,
            version: actual_version,
        } => {
            if session_id != session || actual_version != version {
                return Err("The local service identity did not match this launch.".into());
            }
            let parsed = Url::parse(&url)
                .map_err(|_| "The local service returned an invalid address.".to_string())?;
            let query: Vec<_> = parsed.query_pairs().collect();
            if parsed.scheme() != "http"
                || parsed.host_str() != Some("127.0.0.1")
                || parsed.port().is_none_or(|p| p == 0)
                || parsed.path() != "/"
                || !parsed.username().is_empty()
                || parsed.password().is_some()
                || parsed.fragment().is_some()
                || query.len() != 1
                || query[0].0 != "desktop_session"
                || query[0].1 != session
            {
                return Err("The local service returned an unexpected address.".into());
            }
            Ok(parsed)
        }
        HostEvent::Error {
            message,
            session_id,
        } => {
            if session_id != session {
                return Err("The local service identity did not match this launch.".into());
            }
            Err(message
                .replace(session, "[session]")
                .chars()
                .take(2000)
                .collect())
        }
    }
}

pub fn same_origin(url: &Url, expected: &Option<String>) -> bool {
    url.scheme() == "http"
        && url.host_str() == Some("127.0.0.1")
        && expected
            .as_ref()
            .is_some_and(|origin| url.origin().ascii_serialization() == *origin)
        && url.username().is_empty()
        && url.password().is_none()
}

pub fn external_url(url: &Url) -> bool {
    matches!(url.scheme(), "https" | "http")
        && url.username().is_empty()
        && url.password().is_none()
        && match url.host() {
            Some(url::Host::Domain(host)) => host != "localhost" && !host.ends_with(".localhost"),
            Some(url::Host::Ipv4(address)) => !address.is_loopback() && !address.is_unspecified(),
            Some(url::Host::Ipv6(address)) => {
                !address.is_loopback()
                    && !address.is_unspecified()
                    && address
                        .to_ipv4_mapped()
                        .is_none_or(|ipv4| !ipv4.is_loopback() && !ipv4.is_unspecified())
            }
            None => false,
        }
}

pub fn downloadable(url: &Url, origin: &Option<String>) -> bool {
    same_origin(url, origin)
        || (url.scheme() == "blob"
            && Url::parse(url.path()).is_ok_and(|inside| same_origin(&inside, origin)))
}

#[cfg(test)]
mod tests {
    use super::*;
    fn event(url: &str) -> HostEvent {
        HostEvent::Ready {
            url: url.into(),
            session_id: "abc".into(),
            version: "1".into(),
        }
    }
    #[test]
    fn ready_must_belong_to_this_launch_and_loopback() {
        assert!(ready_url(
            event("http://127.0.0.1:56789/?desktop_session=abc"),
            "abc",
            "1"
        )
        .is_ok());
        for bad in [
            "https://127.0.0.1:56789/?desktop_session=abc",
            "http://localhost:56789/?desktop_session=abc",
            "http://127.0.0.1:0/?desktop_session=abc",
            "http://127.0.0.1:56789/?desktop_session=other",
            "http://127.0.0.1:56789/?desktop_session=abc&extra=1",
            "http://127.0.0.1:56789/path?desktop_session=abc",
            "http://user@127.0.0.1:56789/?desktop_session=abc",
            "http://127.0.0.1:56789/?desktop_session=abc#x",
        ] {
            assert!(ready_url(event(bad), "abc", "1").is_err(), "{bad}");
        }
        assert!(ready_url(
            event("http://127.0.0.1:56789/?desktop_session=abc"),
            "abc",
            "2"
        )
        .is_err());
    }
    #[test]
    fn downloads_and_navigation_do_not_cross_sessions() {
        let origin = Some("http://127.0.0.1:56789".into());
        assert!(downloadable(
            &Url::parse("blob:http://127.0.0.1:56789/example").unwrap(),
            &origin
        ));
        assert!(!downloadable(
            &Url::parse("blob:http://127.0.0.1:56790/example").unwrap(),
            &origin
        ));
        assert!(!downloadable(
            &Url::parse("file:///tmp/x").unwrap(),
            &origin
        ));
        assert!(!external_url(
            &Url::parse("http://127.0.0.1:8765/").unwrap()
        ));
        assert!(!external_url(
            &Url::parse("http://127.2.3.4:8765/").unwrap()
        ));
        assert!(!external_url(&Url::parse("http://[::1]:8765/").unwrap()));
        assert!(!external_url(
            &Url::parse("http://[::ffff:127.0.0.1]:8765/").unwrap()
        ));
        assert!(!external_url(&Url::parse("http://app.localhost/").unwrap()));
        assert!(!external_url(&Url::parse("javascript:alert(1)").unwrap()));
        assert!(external_url(
            &Url::parse("https://github.com/WeStrainGroup/WeCFU").unwrap()
        ));
    }
}
