import React, { useState } from 'react'
import axios from 'axios'
import { Calculator, MapPin, Loader2, Camera, ExternalLink, Settings2, Car, Home, Building2, UserCheck } from 'lucide-react'

function App() {
    const [activeTab, setActiveTab] = useState('taxman')
    const [loading, setLoading] = useState(false)
    const [result, setResult] = useState(null)

    const [taxData, setTaxData] = useState({
        salary: 3000, period: 'month', tax_year: '2025/26', region: 'UK',
        age: 'under 65', student_loan: 'No', pension_amount: 0, pension_type: '£',
        allowances: 0, tax_code: '', married: false, blind: false, no_ni: false
    })

    const [postcode, setPostcode] = useState('LS278RR')
    const [plate, setPlate] = useState('BD51SMM')

    const [hpiData, setHpiData] = useState({
        locationMode: 'optionRegion', region: 'Greater London', postcode: '',
        property_value: 300000, from_year: 2020, from_quarter: 1, to_year: 2025, to_quarter: 1
    })
    const updateHpiData = (key, value) => setHpiData(prev => ({ ...prev, [key]: value }))

    const [lpsData, setLpsData] = useState({
        search_type: 'postcode', postcode: '', property_number: '', max_pages: 3, fetch_details: true,
    })
    const updateLpsData = (key, value) => setLpsData(prev => ({ ...prev, [key]: value }))

    const [lrData, setLrData] = useState({
        username: '', password: '', customer_reference: '', title_number: '',
        flat: '', house: '', street: '', town: '', postcode: '',
        order_register: true, order_title_plan: true
    })
    const updateLrData = (key, value) => setLrData(prev => ({ ...prev, [key]: value }))

    const [iduData, setIduData] = useState({
        username: '', password: '', forename: '', middlename: '', surname: '',
        dd: '', mm: '', yyyy: '', gender: '', reference: '',
        house: '', street: '', town: '', postcode: '',
        email: '', email2: '', mobile: '', mobile2: '', landline: '', landline2: ''
    })
    const updateIduData = (key, value) => setIduData(prev => ({ ...prev, [key]: value }))

    const [iduSessionId, setIduSessionId] = useState(null)
    const [iduStatus, setIduStatus] = useState('idle') // idle | starting | awaiting_otp | processing | complete | error
    const [otpInput, setOtpInput] = useState('')

    const startPolling = (sessionId) => {
        const interval = setInterval(async () => {
            try {
                const res = await axios.get(`/api/scrapers/idu/result/${sessionId}`)
                if (res.data.status === 'complete') {
                    clearInterval(interval)
                    setResult(res.data.result)
                    setIduStatus('complete')
                    setLoading(false)
                } else if (res.data.status === 'awaiting_otp') {
                    // This is the key change: update status so UI shows OTP input
                    setIduStatus('awaiting_otp')
                } else if (res.data.status === 'processing') {
                    setIduStatus('processing')
                } else if (res.data.status === 'error') {
                    clearInterval(interval)
                    setIduStatus('error')
                    setLoading(false)
                    alert("IDU Scraper Error: " + res.data.message)
                }
            } catch (err) {
                console.error("Polling error", err)
            }
        }, 3000)
    }

    const submitOtp = async () => {
        try {
            setIduStatus('processing')
            await axios.post('/api/scrapers/idu/submit-otp', null, {
                params: { session_id: iduSessionId, otp: otpInput }
            })
            // Continue polling - startPolling is already running from handleScrape
        } catch (err) {
            alert("OTP submission failed: " + (err.response?.data?.detail || err.message))
            setIduStatus('awaiting_otp')
        }
    }

    const handleScrape = async (e) => {
        e.preventDefault()
        setResult(null)

        if (activeTab === 'idu') {
            setLoading(true)
            setIduStatus('starting')
            try {
                const res = await axios.post('/api/scrapers/idu/start', null, {
                    params: iduData
                })
                setIduSessionId(res.data.session_id)
                // Start polling immediately - the status will tell us when to show OTP
                startPolling(res.data.session_id)
            } catch (err) {
                alert("Failed to start IDU scraper: " + (err.response?.data?.detail || err.message))
                setIduStatus('error')
                setLoading(false)
            }
            return
        }

        setLoading(true)
        try {
            let endpoint = ''
            let timeout = 120000; // default 2 mins

            if (activeTab === 'taxman') {
                endpoint = `/api/scrapers/taxman?${new URLSearchParams(taxData).toString()}`
            } else if (activeTab === 'council') {
                endpoint = `/api/scrapers/counciltax?postcode=${postcode}`
            } else if (activeTab === 'parkers') {
                endpoint = `/api/scrapers/parkers?plate=${plate}`
            } else if (activeTab === 'nationwide') {
                const params = new URLSearchParams({
                    property_value: hpiData.property_value, from_year: hpiData.from_year,
                    from_quarter: hpiData.from_quarter, to_year: hpiData.to_year, to_quarter: hpiData.to_quarter,
                    ...(hpiData.locationMode === 'optionRegion' && { region: hpiData.region }),
                    ...(hpiData.locationMode === 'optionPostcode' && { postcode: hpiData.postcode }),
                    ...(hpiData.locationMode === 'optionUk' && { region: 'UK' }),
                })
                endpoint = `/api/scrapers/nationwide?${params.toString()}`
            } else if (activeTab === 'lps') {
                const params = new URLSearchParams({
                    search_type: 'postcode', postcode: lpsData.postcode,
                    property_number: lpsData.property_number, max_pages: lpsData.max_pages,
                    fetch_details: lpsData.fetch_details,
                })
                endpoint = `/api/scrapers/lps?${params.toString()}`
            } else if (activeTab === 'landregistry') {
                const params = new URLSearchParams({
                    ...lrData,
                    order_register: lrData.order_register.toString(),
                    order_title_plan: lrData.order_title_plan.toString(),
                })
                endpoint = `/api/scrapers/landregistry?${params.toString()}`
            } else if (activeTab === 'idu') {
                endpoint = `/api/scrapers/idu?${new URLSearchParams(iduData).toString()}`
                timeout = 300000; // 5 mins for IDU
            }

            endpoint += (endpoint.includes('?') ? '&' : '?') + `_t=${Date.now()}`
            const response = await axios.get(endpoint, {
                headers: { 'Cache-Control': 'no-cache', 'Pragma': 'no-cache', 'Expires': '0' },
                timeout: timeout
            })
            setResult(response.data)
        } catch (err) {
            alert("Scraping failed: " + (err.response?.data?.detail || err.message))
        } finally {
            setLoading(false)
        }
    }

    const updateTaxData = (key, value) => setTaxData(prev => ({ ...prev, [key]: value }))

    const renderDetailSection = (data) => {
        if (!data || Object.keys(data).length === 0) return <p style={{ fontSize: '0.8rem', color: '#8b949e' }}>No data</p>
        return Object.entries(data).map(([key, val]) => {
            let displayValue = val
            let status = null
            if (val && typeof val === 'object' && 'value' in val) {
                displayValue = val.value
                status = val.status
            }
            if (Array.isArray(displayValue)) {
                displayValue = displayValue.filter(v => v).join(', ')
            }
            const statusColor = status === 'verified' ? '#56d364' : status === 'not_verified' ? '#f6b93b' : '#8b949e'
            return (
                <div key={key} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                    <span style={{ color: '#8b949e', fontSize: '0.75rem' }}>{key}</span>
                    <span style={{ fontSize: '0.75rem', fontWeight: '500', color: statusColor, textAlign: 'right' }}>
                        {displayValue || 'No data'}
                        {status && (
                            <span style={{ marginLeft: 6, fontSize: '0.65rem', opacity: 0.6 }}>
                                ({status.replace('_', ' ')})
                            </span>
                        )}
                    </span>
                </div>
            )
        })
    }

    const statusBadge = (status) => {
        const s = status?.toLowerCase()
        if (s === 'pass' || s === 'match') return (
            <span style={{ padding: '2px 8px', background: 'rgba(86,211,100,0.15)', color: '#56d364', borderRadius: 4, fontSize: '0.7rem', fontWeight: 'bold' }}>✓ Pass</span>
        )
        if (s === 'alert' || s === 'fail') return (
            <span style={{ padding: '2px 8px', background: 'rgba(248,81,73,0.15)', color: '#f85149', borderRadius: 4, fontSize: '0.7rem', fontWeight: 'bold' }}>✗ Alert</span>
        )
        return (
            <span style={{ padding: '2px 8px', background: 'rgba(139,148,158,0.15)', color: '#8b949e', borderRadius: 4, fontSize: '0.7rem' }}>— Not Checked</span>
        )
    }

    const cleanLabel = (label) => label.replace(/ x$/, '').replace(/ !$/, '')

    const ScreenshotPreview = ({ url }) => {
        const [expanded, setExpanded] = React.useState(false)
        if (!url) return null
        return (
            <div style={{ marginTop: 16, border: '1px solid #374151', borderRadius: 8, overflow: 'hidden' }}>
                <div 
                    style={{ 
                        display: 'flex', 
                        alignItems: 'center', 
                        justifyContent: 'space-between', 
                        padding: '12px 16px', 
                        background: '#1f2937', 
                        cursor: 'pointer' 
                    }}
                    onClick={() => setExpanded(!expanded)}
                    onMouseEnter={e => e.currentTarget.style.background = '#374151'}
                    onMouseLeave={e => e.currentTarget.style.background = '#1f2937'}
                >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <Camera size={16} color="#a371f7" />
                        <span style={{ fontSize: '0.875rem', fontWeight: '500', color: '#e5e7eb' }}>Page Screenshot</span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                        <a 
                            href={url} target="_blank" rel="noopener noreferrer" 
                            onClick={e => e.stopPropagation()}
                            style={{ 
                                fontSize: '0.75rem', 
                                color: '#a371f7', 
                                textDecoration: 'none',
                                display: 'flex',
                                alignItems: 'center',
                                gap: 4
                            }}
                        >
                            <ExternalLink size={12} /> Open full size
                        </a>
                        <span style={{ color: '#9ca3af', fontSize: '0.75rem' }}>{expanded ? '▲ Hide' : '▼ Show'}</span>
                    </div>
                </div>
                {expanded && (
                    <div style={{ background: '#0d1117', padding: 12 }}>
                        <img 
                            src={url} alt="Scraper screenshot" 
                            style={{ width: '100%', borderRadius: 4, border: '1px solid #374151', cursor: 'zoom-in' }}
                            onClick={() => window.open(url, '_blank')}
                        />
                    </div>
                )}
            </div>
        )
    }

    return (
        <div className="app-container">
            <h1>Scraper API Control</h1>

            <div className="tabs-container">
                {[
                    { id: 'taxman', label: 'Listen To Taxman', icon: <Calculator size={18} /> },
                    { id: 'council', label: 'Council Tax', icon: <MapPin size={18} /> },
                    { id: 'parkers', label: 'Parkers', icon: <Car size={18} /> },
                    { id: 'nationwide', label: 'Nationwide HPI', icon: <Home size={18} /> },
                    { id: 'lps', label: 'LPS Valuation', icon: <Building2 size={18} /> },
                    { id: 'landregistry', label: 'Land Registry', icon: <Building2 size={18} /> },
                    { id: 'idu', label: 'IDU', icon: <UserCheck size={18} /> },
                ].map(tab => (
                    <button key={tab.id} className={`tab ${activeTab === tab.id ? 'active' : ''}`}
                        onClick={() => { setActiveTab(tab.id); setResult(null); }}>
                        <span style={{ marginRight: 8, verticalAlign: 'middle' }}>{tab.icon}</span>
                        {tab.label}
                    </button>
                ))}
            </div>

            <div className="form-card">
                <form onSubmit={handleScrape}>
                    {activeTab === 'taxman' && (
                        <div className="form-grid">
                            <div className="form-group">
                                <label>Salary Amount</label>
                                <input type="number" className="input-field" value={taxData.salary} onChange={e => updateTaxData('salary', e.target.value)} />
                            </div>
                            <div className="form-group">
                                <label>Salary Period</label>
                                <select className="input-field" value={taxData.period} onChange={e => updateTaxData('period', e.target.value)}>
                                    <option value="year">Yearly</option><option value="month">Monthly</option>
                                    <option value="4weeks">4 Weekly</option><option value="week">Weekly</option>
                                    <option value="day">Daily</option><option value="hour">Hourly</option>
                                </select>
                            </div>
                            <div className="form-group">
                                <label>Tax Year</label>
                                <select className="input-field" value={taxData.tax_year} onChange={e => updateTaxData('tax_year', e.target.value)}>
                                    <option value="2025/26">2025/26</option><option value="2024/25">2024/25</option><option value="2023/24">2023/24</option>
                                </select>
                            </div>
                            <div className="form-group">
                                <label>Region</label>
                                <select className="input-field" value={taxData.region} onChange={e => updateTaxData('region', e.target.value)}>
                                    <option value="UK">UK (England, NI, Wales)</option><option value="Scotland">Scotland</option>
                                </select>
                            </div>
                            <div className="form-group">
                                <label>Pension Contribution</label>
                                <div style={{ display: 'flex', gap: 5 }}>
                                    <input type="number" className="input-field" style={{ flex: 1 }} value={taxData.pension_amount} onChange={e => updateTaxData('pension_amount', e.target.value)} />
                                    <select className="input-field" style={{ width: 60 }} value={taxData.pension_type} onChange={e => updateTaxData('pension_type', e.target.value)}>
                                        <option value="£">£</option><option value="%">%</option>
                                    </select>
                                </div>
                            </div>
                            <div className="form-group">
                                <label>Additional Allowances (£)</label>
                                <input type="number" className="input-field" value={taxData.allowances} onChange={e => updateTaxData('allowances', e.target.value)} />
                            </div>
                            <div className="form-group">
                                <label>Tax Code (Optional)</label>
                                <input type="text" className="input-field" value={taxData.tax_code} onChange={e => updateTaxData('tax_code', e.target.value)} placeholder="e.g. 1257L" />
                            </div>
                            <div className="form-group">
                                <label>Student Loan</label>
                                <select className="input-field" value={taxData.student_loan} onChange={e => updateTaxData('student_loan', e.target.value)}>
                                    <option value="No">No Student Loan</option><option value="Plan 1">Plan 1</option>
                                    <option value="Plan 2">Plan 2</option><option value="Plan 4">Plan 4 (Scottish)</option>
                                    <option value="Postgraduate">Postgraduate</option>
                                </select>
                            </div>
                            <div className="form-group checkbox-group" style={{ gridColumn: 'span 2' }}>
                                {[['married','Married Allowance'],['blind','Blind Allowance'],['no_ni','Exempt from NI']].map(([key, label]) => (
                                    <label key={key} style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer' }}>
                                        <input type="checkbox" checked={taxData[key]} onChange={e => updateTaxData(key, e.target.checked)} />{label}
                                    </label>
                                ))}
                            </div>
                        </div>
                    )}

                    {activeTab === 'council' && (
                        <div className="form-group">
                            <label>Postcode</label>
                            <input type="text" className="input-field" value={postcode} onChange={e => setPostcode(e.target.value)} placeholder="e.g. SW1A 1AA" />
                        </div>
                    )}

                    {activeTab === 'parkers' && (
                        <div className="form-group">
                            <label>Car Registration Plate</label>
                            <input type="text" className="input-field" value={plate} onChange={e => setPlate(e.target.value)} placeholder="e.g. BD51 SMM" style={{ textTransform: 'uppercase' }} />
                        </div>
                    )}

                    {activeTab === 'nationwide' && (
                        <div className="form-grid">
                            <div className="form-group" style={{ gridColumn: 'span 2' }}>
                                <label>Tell us where the property is</label>
                                <div style={{ display: 'flex', gap: 20, marginTop: 8 }}>
                                    {[['optionRegion','Region'],['optionPostcode','Postcode'],['optionUk','UK average']].map(([val, lbl]) => (
                                        <label key={val} style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', color: 'var(--text-dim)', fontSize: '0.9rem' }}>
                                            <input type="radio" name="locationMode" value={val} checked={hpiData.locationMode === val} onChange={e => updateHpiData('locationMode', e.target.value)} />{lbl}
                                        </label>
                                    ))}
                                </div>
                            </div>
                            {hpiData.locationMode === 'optionRegion' && (
                                <div className="form-group" style={{ gridColumn: 'span 2' }}>
                                    <label>Region</label>
                                    <select className="input-field" value={hpiData.region} onChange={e => updateHpiData('region', e.target.value)}>
                                        {['East Anglia','East Midlands','Greater London','North','North West','Northern Ireland','Outer Metropolitan','Outer South East','Scotland','South West','Wales','West Midlands','Yorkshire & The Humber'].map(r => <option key={r}>{r}</option>)}
                                    </select>
                                </div>
                            )}
                            {hpiData.locationMode === 'optionPostcode' && (
                                <div className="form-group" style={{ gridColumn: 'span 2' }}>
                                    <label>Enter Postcode</label>
                                    <input type="text" className="input-field" value={hpiData.postcode} onChange={e => updateHpiData('postcode', e.target.value.toUpperCase())} placeholder="e.g. SW1A 1AA" style={{ maxWidth: 160 }} />
                                </div>
                            )}
                            {hpiData.locationMode === 'optionUk' && (
                                <div className="form-group" style={{ gridColumn: 'span 2' }}>
                                    <p style={{ color: 'var(--text-dim)', fontSize: '0.85rem', padding: '8px 12px', background: 'rgba(255,255,255,0.04)', borderRadius: 8 }}>Using UK national average price data</p>
                                </div>
                            )}
                            <div className="form-group" style={{ gridColumn: 'span 2' }}>
                                <label>Property Value (£)</label>
                                <input type="number" className="input-field" value={hpiData.property_value} onChange={e => updateHpiData('property_value', e.target.value)} />
                            </div>
                            <div className="form-group"><label>From Year</label><input type="number" className="input-field" value={hpiData.from_year} onChange={e => updateHpiData('from_year', parseInt(e.target.value))} /></div>
                            <div className="form-group">
                                <label>From Quarter</label>
                                <select className="input-field" value={hpiData.from_quarter} onChange={e => updateHpiData('from_quarter', parseInt(e.target.value))}>
                                    {[1,2,3,4].map(q => <option key={q} value={q}>Q{q}</option>)}
                                </select>
                            </div>
                            <div className="form-group"><label>To Year</label><input type="number" className="input-field" value={hpiData.to_year} onChange={e => updateHpiData('to_year', parseInt(e.target.value))} /></div>
                            <div className="form-group">
                                <label>To Quarter</label>
                                <select className="input-field" value={hpiData.to_quarter} onChange={e => updateHpiData('to_quarter', parseInt(e.target.value))}>
                                    {[1,2,3,4].map(q => <option key={q} value={q}>Q{q}</option>)}
                                </select>
                            </div>
                        </div>
                    )}

                    {activeTab === 'lps' && (
                        <div className="form-grid">
                            <div className="form-group">
                                <label>Postcode</label>
                                <input type="text" className="input-field" value={lpsData.postcode} onChange={e => updateLpsData('postcode', e.target.value.toUpperCase())} placeholder="e.g. BT1 5GS" />
                            </div>
                            <div className="form-group">
                                <label>House/Property Number (optional)</label>
                                <input type="text" className="input-field" value={lpsData.property_number} onChange={e => updateLpsData('property_number', e.target.value)} placeholder="e.g. 2" />
                            </div>
                            <div className="form-group">
                                <label>Max Pages (default 3)</label>
                                <input type="number" className="input-field" min="1" max="20" value={lpsData.max_pages} onChange={e => updateLpsData('max_pages', parseInt(e.target.value))} />
                            </div>
                        </div>
                    )}

                    {activeTab === 'landregistry' && (
                        <div className="form-grid">
                            <div className="form-group" style={{ gridColumn: 'span 2' }}>
                                <label>Customer Reference</label>
                                <input type="text" className="input-field" value={lrData.customer_reference} onChange={e => updateLrData('customer_reference', e.target.value)} />
                            </div>
                            <div className="form-group" style={{ gridColumn: 'span 2' }}>
                                <label>Title Number</label>
                                <input type="text" className="input-field" value={lrData.title_number} onChange={e => updateLrData('title_number', e.target.value.toUpperCase())} placeholder="e.g. SGL123456" />
                                <p style={{ marginTop: 6, fontSize: '0.8rem', color: 'var(--text-dim)' }}>Or search by property details below</p>
                            </div>
                            <div className="form-group"><label>Flat</label><input type="text" className="input-field" value={lrData.flat} onChange={e => updateLrData('flat', e.target.value)} /></div>
                            <div className="form-group"><label>House</label><input type="text" className="input-field" value={lrData.house} onChange={e => updateLrData('house', e.target.value)} /></div>
                            <div className="form-group"><label>Street</label><input type="text" className="input-field" value={lrData.street} onChange={e => updateLrData('street', e.target.value)} /></div>
                            <div className="form-group"><label>Town / City</label><input type="text" className="input-field" value={lrData.town} onChange={e => updateLrData('town', e.target.value)} /></div>
                            <div className="form-group" style={{ gridColumn: 'span 2' }}>
                                <label>Postcode</label>
                                <input type="text" className="input-field" value={lrData.postcode} onChange={e => updateLrData('postcode', e.target.value.toUpperCase())} placeholder="e.g. SW1A 1AA" />
                            </div>
                            <div className="form-group checkbox-group" style={{ gridColumn: 'span 2' }}>
                                {[['order_register','Register'],['order_title_plan','Title Plan']].map(([key, label]) => (
                                    <label key={key} style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer' }}>
                                        <input type="checkbox" checked={lrData[key]} onChange={e => updateLrData(key, e.target.checked)} />{label}
                                    </label>
                                ))}
                            </div>
                        </div>
                    )}

                    {activeTab === 'idu' && (
                        <div className="form-grid">
                            <div className="form-group">
                                <label>Tracesmart Username</label>
                                <input type="text" className="input-field" value={iduData.username} onChange={e => updateIduData('username', e.target.value)} />
                            </div>
                            <div className="form-group">
                                <label>Tracesmart Password</label>
                                <input type="password" className="input-field" value={iduData.password} onChange={e => updateIduData('password', e.target.value)} />
                            </div>
                            <div className="form-group">
                                <label>Forename *</label>
                                <input type="text" className="input-field" required value={iduData.forename} onChange={e => updateIduData('forename', e.target.value)} />
                            </div>
                            <div className="form-group">
                                <label>Middle Name</label>
                                <input type="text" className="input-field" value={iduData.middlename} onChange={e => updateIduData('middlename', e.target.value)} />
                            </div>
                            <div className="form-group">
                                <label>Surname *</label>
                                <input type="text" className="input-field" required value={iduData.surname} onChange={e => updateIduData('surname', e.target.value)} />
                            </div>
                            <div className="form-group">
                                <label>Date of Birth (DD / MM / YYYY)</label>
                                <div style={{ display: 'flex', gap: 5 }}>
                                    <input type="text" placeholder="DD" className="input-field" style={{ width: '33%' }} value={iduData.dd} onChange={e => updateIduData('dd', e.target.value)} />
                                    <input type="text" placeholder="MM" className="input-field" style={{ width: '33%' }} value={iduData.mm} onChange={e => updateIduData('mm', e.target.value)} />
                                    <input type="text" placeholder="YYYY" className="input-field" style={{ width: '33%' }} value={iduData.yyyy} onChange={e => updateIduData('yyyy', e.target.value)} />
                                </div>
                            </div>
                            <div className="form-group">
                                <label>Gender</label>
                                <select className="input-field" value={iduData.gender} onChange={e => updateIduData('gender', e.target.value)}>
                                    <option value="">Select</option>
                                    <option value="Male">Male</option>
                                    <option value="Female">Female</option>
                                </select>
                            </div>
                            <div className="form-group">
                                <label>Reference</label>
                                <input type="text" className="input-field" value={iduData.reference} onChange={e => updateIduData('reference', e.target.value)} />
                            </div>
                            <div className="form-group"><label>House</label><input type="text" className="input-field" value={iduData.house} onChange={e => updateIduData('house', e.target.value)} /></div>
                            <div className="form-group"><label>Street</label><input type="text" className="input-field" value={iduData.street} onChange={e => updateIduData('street', e.target.value)} /></div>
                            <div className="form-group"><label>Town</label><input type="text" className="input-field" value={iduData.town} onChange={e => updateIduData('town', e.target.value)} /></div>
                            <div className="form-group"><label>Postcode</label><input type="text" className="input-field" value={iduData.postcode} onChange={e => updateIduData('postcode', e.target.value.toUpperCase())} /></div>
                            <div className="form-group"><label>Email 1</label><input type="email" className="input-field" value={iduData.email} onChange={e => updateIduData('email', e.target.value)} /></div>
                            <div className="form-group"><label>Email 2</label><input type="email" className="input-field" value={iduData.email2} onChange={e => updateIduData('email2', e.target.value)} /></div>
                            <div className="form-group"><label>Mobile 1</label><input type="text" className="input-field" value={iduData.mobile} onChange={e => updateIduData('mobile', e.target.value)} /></div>
                            <div className="form-group"><label>Mobile 2</label><input type="text" className="input-field" value={iduData.mobile2} onChange={e => updateIduData('mobile2', e.target.value)} /></div>
                            <div className="form-group"><label>Landline 1</label><input type="text" className="input-field" value={iduData.landline} onChange={e => updateIduData('landline', e.target.value)} /></div>
                            <div className="form-group"><label>Landline 2</label><input type="text" className="input-field" value={iduData.landline2} onChange={e => updateIduData('landline2', e.target.value)} /></div>
                        </div>
                    )}

                    <button className="submit-btn" disabled={loading || iduStatus === 'awaiting_otp'}>
                        {loading ? (
                            <div style={{ display: 'flex', alignItems: 'center', gap: 10, justifyContent: 'center' }}>
                                <span className="loading-spinner"></span>
                                <span>
                                    {iduStatus === 'starting' ? 'Initializing IDU...' : 
                                     iduStatus === 'processing' ? 'Processing Search...' : 
                                     'Running Scraper...'}
                                </span>
                            </div>
                        ) : 'Run Scraper'}
                    </button>
                </form>

                {activeTab === 'idu' && iduStatus === 'awaiting_otp' && (
                    <div style={{ 
                        marginTop: 20, 
                        padding: 20, 
                        background: 'rgba(88,166,255,0.1)', 
                        border: '1px solid #58a6ff', 
                        borderRadius: 8,
                        textAlign: 'center'
                    }}>
                        <p style={{ marginBottom: 15, color: '#fff' }}>
                            A One Time Password has been sent to your email. <br/>
                            Enter it below to continue:
                        </p>
                        <div style={{ display: 'flex', gap: 10, justifyContent: 'center' }}>
                            <input 
                                type="text" 
                                className="input-field" 
                                style={{ width: 160, textAlign: 'center', fontSize: '1.2rem', letterSpacing: 4 }}
                                value={otpInput} 
                                onChange={e => setOtpInput(e.target.value)} 
                                placeholder="123456" 
                                maxLength={6} 
                            />
                            <button className="submit-btn" style={{ width: 'auto', padding: '0 20px' }} onClick={submitOtp}>
                                Submit OTP
                            </button>
                        </div>
                    </div>
                )}
            </div>

            {result && (
                <div className="results-container">
                    <div className="data-card">
                        <h3 style={{ marginBottom: 20, display: 'flex', alignItems: 'center', gap: 10 }}>
                            <ExternalLink size={20} color="#58a6ff" />
                            Scraped Data
                        </h3>

                        {activeTab === 'taxman' && (
                            <div>
                                <table>
                                    <thead><tr><th>Label</th><th>Yearly</th><th>Monthly</th></tr></thead>
                                    <tbody>
                                        {result.payslip?.slice(1).map((row, idx) => (
                                            <tr key={idx}>
                                                <td>{row.label}</td><td>{row.yearly}</td>
                                                <td style={{ color: row.label === 'Net Wage' ? '#58a6ff' : '' }}>{row.monthly}</td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                                <ScreenshotPreview url={result.screenshot_url} />
                            </div>
                        )}

                        {activeTab === 'council' && (
                            <div>
                                <table>
                                    <thead><tr><th>Address</th><th>Band</th><th>Monthly</th></tr></thead>
                                    <tbody>
                                        {result.properties?.map((prop, idx) => (
                                            <tr key={idx}>
                                                <td style={{ fontSize: '0.8rem' }}>{prop.address}</td>
                                                <td style={{ fontWeight: 'bold', color: '#9646ff' }}>{prop.band}</td>
                                                <td>£{prop.monthly_amount}</td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                                <ScreenshotPreview url={result.screenshot_url} />
                            </div>
                        )}

                        {activeTab === 'parkers' && result && (
                            <div style={{ background: 'rgba(23, 37, 84, 0.4)', border: '1px solid rgba(30, 58, 138, 0.5)', borderRadius: 8, padding: 16, marginTop: 16 }}>
                                
                                {/* NOT FOUND STATE */}
                                {(result.error === 'not_found' || 
                                  result.message === 'not_found' || 
                                  (!result.make && !result.reg_plate)) && (
                                    <div style={{ textAlign: 'center', padding: '32px 0' }}>
                                        <div style={{ fontSize: '3.75rem', marginBottom: 16 }}>🚗</div>
                                        <h3 style={{ color: '#fde047', fontWeight: '600', fontSize: '1.25rem', marginBottom: 12 }}>
                                            Vehicle Not Found in Parkers Database
                                        </h3>
                                        <p style={{ color: '#d1d5db', fontSize: '0.875rem', lineHeight: '1.625', maxWidth: 448, margin: '0 auto' }}>
                                            The registration plate <strong style={{ color: '#fff', fontFamily: 'monospace' }}>
                                            {result.plate || plate}</strong> could not be located in the 
                                            Parkers database. This may occur if the vehicle was registered 
                                            before 2006, is not UK-registered, or the plate was entered 
                                            incorrectly. Please verify the registration and try again.
                                        </p>
                                    </div>
                                )}

                                {/* SUCCESS STATE */}
                                {result.make && (
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                                        
                                        {/* Vehicle image + header side by side */}
                                        <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
                                            {result.vehicle_image && (
                                                <img 
                                                    src={result.vehicle_image} 
                                                    alt={result.vehicle_full_name} 
                                                    style={{ width: 192, height: 128, objectFit: 'cover', borderRadius: 8, border: '1px solid #1d4ed8', flexShrink: 0 }}
                                                    onError={e => e.target.style.display='none'} 
                                                />
                                            )}
                                            <div style={{ flex: 1 }}>
                                                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                                                    <Car size={20} color="#60a5fa" />
                                                    <h3 style={{ color: '#fff', fontWeight: '700', fontSize: '1.125rem' }}>
                                                        {result.vehicle_full_name}
                                                    </h3>
                                                </div>
                                                <p style={{ color: '#93c5fd', fontSize: '0.875rem', fontFamily: 'monospace', marginBottom: 8 }}>
                                                    {result.reg_plate}
                                                </p>
                                                {result.vehicle_details && 
                                                    Object.entries(result.vehicle_details).map(([k, v]) => (
                                                        <p key={k} style={{ color: '#9ca3af', fontSize: '0.875rem' }}>
                                                            <span style={{ color: '#6b7280' }}>{k}:</span>{' '}
                                                            <span style={{ color: '#e5e7eb' }}>{v}</span>
                                                        </p>
                                                    ))
                                                }
                                            </div>
                                        </div>

                                        {/* Price Cards */}
                                        {result.prices && (
                                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 12 }}>
                                                
                                                {/* Private Sale */}
                                                <div style={{ background: 'rgba(5, 46, 22, 0.5)', border: '1px solid rgba(21, 128, 61, 0.5)', borderRadius: 8, padding: 16, textAlign: 'center' }}>
                                                    <p style={{ color: '#4ade80', fontSize: '0.75rem', textTransform: 'uppercase', trackingWidest: '0.1em', marginBottom: 12, fontWeight: '600' }}>
                                                        🏠 Private Sale
                                                    </p>
                                                    <p style={{ color: '#86efac', fontSize: '1.5rem', fontWeight: '700' }}>
                                                        {result.prices.private_low || '—'}
                                                    </p>
                                                    {result.prices.private_high && (
                                                        <>
                                                            <p style={{ color: '#6b7280', fontSize: '0.75rem', margin: '4px 0' }}>to</p>
                                                            <p style={{ color: '#86efac', fontSize: '1.5rem', fontWeight: '700' }}>
                                                                {result.prices.private_high}
                                                            </p>
                                                        </>
                                                    )}
                                                </div>

                                                {/* Dealer Price */}
                                                <div style={{ background: 'rgba(23, 37, 84, 0.5)', border: '1px solid rgba(37, 99, 235, 0.5)', borderRadius: 8, padding: 16, textAlign: 'center' }}>
                                                    <p style={{ color: '#60a5fa', fontSize: '0.75rem', textTransform: 'uppercase', trackingWidest: '0.1em', marginBottom: 12, fontWeight: '600' }}>
                                                        🏪 Dealer / Forecourt
                                                    </p>
                                                    <p style={{ color: '#93c5fd', fontSize: '1.5rem', fontWeight: '700' }}>
                                                        {result.prices.dealer_low || '—'}
                                                    </p>
                                                    {result.prices.dealer_high && (
                                                        <>
                                                            <p style={{ color: '#6b7280', fontSize: '0.75rem', margin: '4px 0' }}>to</p>
                                                            <p style={{ color: '#93c5fd', fontSize: '1.5rem', fontWeight: '700' }}>
                                                                {result.prices.dealer_high}
                                                            </p>
                                                        </>
                                                    )}
                                                </div>

                                                {/* Part Exchange - only if available */}
                                                {result.prices.part_exchange && (
                                                    <div style={{ gridColumn: 'span 2', background: 'rgba(66, 32, 6, 0.5)', border: '1px solid rgba(161, 98, 7, 0.5)', borderRadius: 8, padding: 16, textAlign: 'center' }}>
                                                        <p style={{ color: '#facc15', fontSize: '0.75rem', textTransform: 'uppercase', trackingWidest: '0.1em', marginBottom: 12, fontWeight: '600' }}>
                                                            🔄 Part Exchange
                                                        </p>
                                                        <p style={{ color: '#fde047', fontSize: '1.5rem', fontWeight: '700' }}>
                                                            {result.prices.part_exchange}
                                                        </p>
                                                    </div>
                                                )}

                                                {/* No prices available */}
                                                {!result.prices.private_low && !result.prices.dealer_low && (
                                                    <div style={{ gridColumn: 'span 2', padding: 16, border: '1px solid rgba(161, 98, 7, 0.5)', background: 'rgba(66, 32, 6, 0.3)', borderRadius: 8, textAlign: 'center' }}>
                                                        <p style={{ color: '#fde047', fontSize: '0.875rem' }}>
                                                            Vehicle identified but pricing data was not available. 
                                                            This vehicle may be too old or unlisted in Parkers free valuation database.
                                                        </p>
                                                    </div>
                                                )}
                                            </div>
                                        )}

                                        {/* Screenshot */}
                                        <ScreenshotPreview url={result.screenshot_url} />

                                    </div>
                                )}
                            </div>
                        )}

                        {activeTab === 'nationwide' && (
                            <div>
                                <div style={{ marginBottom: 20, padding: 15, background: 'rgba(255,255,255,0.05)', borderRadius: 10 }}>
                                    <p style={{ color: '#8b949e', fontSize: '0.9rem' }}>{result.description}</p>
                                </div>
                                <table>
                                    <thead><tr><th>Period</th><th>Estimated Value</th></tr></thead>
                                    <tbody>
                                        <tr><td>{result.from_label}</td><td>{result.from_value}</td></tr>
                                        <tr><td>{result.to_label}</td><td style={{ color: '#58a6ff', fontWeight: 'bold' }}>{result.to_value}</td></tr>
                                        <tr><td>Percentage Change</td><td style={{ color: '#9646ff', fontWeight: 'bold' }}>{result.percentage_change}</td></tr>
                                    </tbody>
                                </table>
                                <ScreenshotPreview url={result.screenshot_url} />
                            </div>
                        )}

                        {activeTab === 'lps' && (
                            <div>
                                <div style={{ marginBottom: 16, padding: '10px 15px', background: 'rgba(255,255,255,0.05)', borderRadius: 8 }}>
                                    <span style={{ color: '#8b949e', fontSize: '0.85rem' }}>{result.total_found} properties found across {result.pages_scraped} page(s)</span>
                                </div>
                                {result.property_details && result.property_details.map((detail, i) => (
                                    <div key={i} style={{ marginBottom: 32, borderTop: '1px solid rgba(255,255,255,0.1)', paddingTop: 20 }}>
                                        <h3 style={{ color: '#58a6ff', marginBottom: 8, fontSize: '0.95rem' }}>{result.properties[i]?.full_address}</h3>
                                        <div style={{ display: 'flex', gap: 20, marginBottom: 12, flexWrap: 'wrap' }}>
                                            {[['ID', detail.property_id],['UPRN', detail.uprn],['Type', detail.property_type],
                                              ['Capital Value', result.properties[i]?.capital_value],['Total NAV', result.properties[i]?.total_nav]
                                            ].map(([lbl, val]) => (
                                                <span key={lbl} style={{ color: '#8b949e', fontSize: '0.8rem' }}>{lbl}: <strong style={{ color: '#fff' }}>{val}</strong></span>
                                            ))}
                                        </div>
                                        {detail.estimated_rate_bill && (
                                            <div style={{ marginBottom: 12, padding: '8px 12px', background: 'rgba(86,211,100,0.08)', borderRadius: 6, display: 'inline-block' }}>
                                                <span style={{ color: '#56d364', fontSize: '0.85rem' }}>Est. Rate Bill: <strong>{detail.estimated_rate_bill}</strong></span>
                                            </div>
                                        )}
                                        {detail.valuation_summaries?.length > 0 && (
                                            <table style={{ width: '100%', marginTop: 8 }}>
                                                <thead><tr><th>#</th><th>Floor</th><th>Use</th><th>Area</th><th>Rate</th><th>Type</th></tr></thead>
                                                <tbody>
                                                    {detail.valuation_summaries.map((s, j) => (
                                                        <tr key={j}><td>{s.num}</td><td>{s.floor}</td><td>{s.description_use}</td><td>{s.area}</td><td>{s.rate}</td><td>{s.distinguishment}</td></tr>
                                                    ))}
                                                </tbody>
                                            </table>
                                        )}
                                        {detail.error && <p style={{ color: '#f85149', fontSize: '0.8rem' }}>Detail error: {detail.error}</p>}
                                    </div>
                                ))}
                                <ScreenshotPreview url={result.screenshot_url} />
                            </div>
                        )}

                        {activeTab === 'landregistry' && (
                            <div>
                                {/* Property summary */}
                                <div style={{ marginBottom: 20, padding: 15, background: 'rgba(255,255,255,0.05)', borderRadius: 10 }}>
                                    <p style={{ color: '#8b949e', fontSize: '0.85rem', marginBottom: 4 }}>Title Number</p>
                                    <p style={{ fontSize: '1.1rem', fontWeight: 'bold', color: '#58a6ff' }}>{result.title_number}</p>
                                    <p style={{ color: '#8b949e', fontSize: '0.85rem', marginTop: 8 }}>{result.address}</p>
                                    <p style={{ color: '#8b949e', fontSize: '0.85rem' }}>Tenure: {result.tenure}</p>
                                    <p style={{ color: '#8b949e', fontSize: '0.85rem' }}>Ref: {result.customer_reference}</p>
                                </div>

                                {result.error && <p style={{ color: '#ff4444', padding: 10 }}>{result.error}</p>}

                                {/* A Register */}
                                {result.register_data?.a_register && (
                                    <div style={{ marginBottom: 24 }}>
                                        <p style={{ color: '#58a6ff', fontWeight: 'bold', marginBottom: 10, fontSize: '0.95rem' }}>
                                            A — Property Register
                                            {result.register_local_path && (
                                                <a href={result.register_local_path} target="_blank" rel="noreferrer"
                                                    style={{ marginLeft: 12, fontSize: '0.75rem', color: '#9646ff' }}>Download PDF ↗</a>
                                            )}
                                        </p>
                                        <table>
                                            <tbody>
                                                {[
                                                    ['Tenure', result.register_data.a_register.tenure],
                                                    ['Property Address', result.register_data.a_register.property_address],
                                                    ['County', result.register_data.a_register.county],
                                                    ['District', result.register_data.a_register.district],
                                                    ['Lease Date', result.register_data.a_register.lease_date],
                                                    ['Lease Term', result.register_data.a_register.lease_term],
                                                    ['Lease Rent', result.register_data.a_register.lease_rent],
                                                    ['Lease Parties', result.register_data.a_register.lease_parties?.join(', ')],
                                                ].filter(([, v]) => v).map(([label, value], i) => (
                                                    <tr key={i}>
                                                        <td style={{ color: '#8b949e', width: 160, fontSize: '0.8rem', paddingRight: 16 }}>{label}</td>
                                                        <td style={{ fontSize: '0.85rem' }}>{value}</td>
                                                    </tr>
                                                ))}
                                            </tbody>
                                        </table>
                                    </div>
                                )}

                                {/* B Register */}
                                {result.register_data?.b_register && (
                                    <div style={{ marginBottom: 24 }}>
                                        <p style={{ color: '#58a6ff', fontWeight: 'bold', marginBottom: 10, fontSize: '0.95rem' }}>B — Proprietorship Register</p>
                                        <table>
                                            <tbody>
                                                {[
                                                    ['Title Class', result.register_data.b_register.title_class],
                                                    ['Proprietor', result.register_data.b_register.proprietor],
                                                    ['Price Paid', result.register_data.b_register.price_paid],
                                                    ['Price Paid Date', result.register_data.b_register.price_paid_date],
                                                ].filter(([, v]) => v).map(([label, value], i) => (
                                                    <tr key={i}>
                                                        <td style={{ color: '#8b949e', width: 160, fontSize: '0.8rem', paddingRight: 16 }}>{label}</td>
                                                        <td style={{ fontSize: '0.85rem' }}>{value}</td>
                                                    </tr>
                                                ))}
                                            </tbody>
                                        </table>
                                        {result.register_data.b_register.restrictions?.map((r, i) => (
                                            <div key={i} style={{ marginTop: 8, padding: '8px 12px', background: 'rgba(246,185,59,0.08)', borderLeft: '3px solid #f6b93b', borderRadius: 4, fontSize: '0.8rem', color: '#8b949e' }}>
                                                <strong style={{ color: '#f6b93b' }}>RESTRICTION {i + 1}: </strong>{r}
                                            </div>
                                        ))}
                                    </div>
                                )}

                                {/* C Register */}
                                {result.register_data?.c_register && (
                                    <div style={{ marginBottom: 24 }}>
                                        <p style={{ color: '#58a6ff', fontWeight: 'bold', marginBottom: 10, fontSize: '0.95rem' }}>
                                            C — Charges Register
                                            <span style={{ marginLeft: 10, fontSize: '0.75rem', color: '#8b949e' }}>
                                                {result.register_data.c_register.charge_count} charge(s)
                                            </span>
                                        </p>
                                        {result.register_data.c_register.charges?.length === 0 && (
                                            <p style={{ color: '#8b949e', fontSize: '0.85rem' }}>No charges registered.</p>
                                        )}
                                        {result.register_data.c_register.charges?.map((charge, i) => (
                                            <div key={i} style={{ marginBottom: 10, padding: '10px 14px', background: 'rgba(255,255,255,0.04)', borderRadius: 8, borderLeft: '3px solid #9646ff' }}>
                                                <p style={{ color: '#fff', fontWeight: 'bold', fontSize: '0.85rem', marginBottom: 4 }}>{charge.lender}</p>
                                                {charge.company_reg && <p style={{ color: '#8b949e', fontSize: '0.78rem' }}>Co. Reg: {charge.company_reg}</p>}
                                                <p style={{ color: '#8b949e', fontSize: '0.78rem' }}>Charge date: {charge.charge_date}</p>
                                                {charge.lender_address && <p style={{ color: '#8b949e', fontSize: '0.78rem' }}>{charge.lender_address}</p>}
                                            </div>
                                        ))}
                                    </div>
                                )}

                                {/* Title Plan */}
                                {result.title_plan_data && (
                                    <div style={{ marginBottom: 24 }}>
                                        <p style={{ color: '#58a6ff', fontWeight: 'bold', marginBottom: 10, fontSize: '0.95rem' }}>
                                            Title Plan
                                            {result.title_plan_local_path && (
                                                <a href={result.title_plan_local_path} target="_blank" rel="noreferrer"
                                                    style={{ marginLeft: 12, fontSize: '0.75rem', color: '#9646ff' }}>Download PDF ↗</a>
                                            )}
                                        </p>
                                        <div style={{ padding: '10px 14px', background: 'rgba(255,255,255,0.04)', borderRadius: 8, fontSize: '0.82rem', color: '#8b949e' }}>
                                            {result.title_plan_data.issued_on && <p>Issued: {result.title_plan_data.issued_on}</p>}
                                            {result.title_plan_data.land_registry_office && <p>Office: {result.title_plan_data.land_registry_office}</p>}
                                            {result.title_plan_data.map_note && <p style={{ marginTop: 6, fontStyle: 'italic' }}>{result.title_plan_data.map_note}</p>}
                                        </div>
                                    </div>
                                )}
                                <ScreenshotPreview url={result.screenshot_url} />
                            </div>
                        )}

                        {activeTab === 'idu' && (
                            <div className="idu-results">
                                <div style={{ textAlign: 'center', marginBottom: 30, padding: 20, background: 'rgba(255,255,255,0.03)', borderRadius: 12 }}>
                                    <h2 style={{ 
                                        fontSize: '2.5rem', 
                                        color: result.verdict?.toUpperCase().includes('PASS') ? '#56d364' : '#f85149',
                                        marginBottom: 5,
                                        textShadow: '0 0 20px rgba(0,0,0,0.3)'
                                    }}>
                                        {result.verdict || 'NO VERDICT'}
                                    </h2>
                                    <p style={{ fontSize: '1.2rem', color: '#8b949e' }}>Score: <strong style={{ color: '#fff' }}>{result.score || '0'}</strong></p>
                                    <p style={{ fontSize: '0.85rem', color: '#8b949e', marginTop: 10 }}>Search ID: {result.search_id} | {result.date_of_search}</p>
                                </div>

                                {result.pep_entries?.length > 0 && (
                                    <div style={{ marginBottom: 25, padding: '15px 20px', background: 'rgba(246,185,59,0.1)', border: '1px solid rgba(246,185,59,0.3)', borderRadius: 10 }}>
                                        <h4 style={{ color: '#f6b93b', display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
                                            ⚠️ PEP / Sanctions Matches Found
                                        </h4>
                                        {result.pep_entries.map((pep, i) => (
                                            <div key={i} style={{ padding: 10, borderBottom: i < result.pep_entries.length - 1 ? '1px solid rgba(246,185,59,0.2)' : 'none' }}>
                                                <p style={{ color: '#fff', fontWeight: 'bold' }}>{pep.name} ({pep.match_score})</p>
                                                <p style={{ fontSize: '0.8rem', color: '#8b949e' }}>{pep.reason} | {pep.country}</p>
                                            </div>
                                        ))}
                                    </div>
                                )}

                                <div style={{ marginBottom: 30 }}>
                                    <h4 style={{ color: '#58a6ff', marginBottom: 15 }}>Summary Items</h4>
                                    <table>
                                        <thead><tr><th>Category</th><th>Label</th><th>Status</th></tr></thead>
                                        <tbody>
                                            {result.summary_items?.map((item, i) => (
                                                <tr key={i}>
                                                    <td style={{ color: '#8b949e', fontSize: '0.85rem' }}>{item.category}</td>
                                                    <td style={{ fontSize: '0.85rem' }}>{cleanLabel(item.label)}</td>
                                                    <td style={{ textAlign: 'center' }}>{statusBadge(item.status)}</td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>

                                <div className="form-grid" style={{ gap: 20 }}>
                                    {[
                                        { title: 'Address Detail', data: result.address_detail },
                                        { title: 'Credit Active', data: result.credit_active },
                                        { title: 'DOB Verification', data: result.dob_verification },
                                        { title: 'Property Detail', data: result.property_detail },
                                        { title: 'CCJ', data: result.ccj },
                                        { title: 'Insolvency', data: result.insolvency },
                                        { title: 'Company Director', data: result.company_director }
                                    ].map((sec, i) => (
                                        <div key={i} style={{ padding: 15, background: 'rgba(255,255,255,0.03)', borderRadius: 10 }}>
                                            <h5 style={{ color: '#58a6ff', marginBottom: 10, fontSize: '0.9rem' }}>{sec.title}</h5>
                                            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                                                {renderDetailSection(sec.data)}
                                            </div>
                                        </div>
                                    ))}
                                </div>

                                {result.address_links?.length > 0 && (
                                    <div style={{ marginTop: 30 }}>
                                        <h4 style={{ color: '#58a6ff', marginBottom: 15 }}>Address Links</h4>
                                        <table>
                                            <thead><tr><th>Address</th><th>Date From</th><th>Date To</th></tr></thead>
                                            <tbody>
                                                {result.address_links.map((link, i) => (
                                                    <tr key={i}>
                                                        <td style={{ fontSize: '0.8rem' }}>{link.address}</td>
                                                        <td style={{ fontSize: '0.8rem' }}>{link.date_from}</td>
                                                        <td style={{ fontSize: '0.8rem' }}>{link.date_to}</td>
                                                    </tr>
                                                ))}
                                            </tbody>
                                        </table>
                                    </div>
                                )}
                                <ScreenshotPreview url={result.screenshot_url} />
                            </div>
                        )}
                    </div>
                </div>
            )}
        </div>
    )
}

export default App