import React, { useState } from 'react'
import axios from 'axios'
import { Calculator, MapPin, Loader2, Camera, ExternalLink, Settings2, Car, Home, Building2, UserCheck, Users, Scale } from 'lucide-react'

function App() {
    const [activeTab, setActiveTab] = useState('taxman')
    const [loading, setLoading] = useState(false)
    const [result, setResult] = useState(null)
    const [scrapeError, setScrapeError] = useState('')

    const [taxData, setTaxData] = useState({
        salary: 3000, period: 'month', tax_year: '2025/26', region: 'UK',
        age: 'under 65', student_loan: 'No', pension_amount: 0, pension_type: '£',
        allowances: 0, tax_code: '', married: false, blind: false, no_ni: false
    })

    const [postcode, setPostcode] = useState('LS278RR')
    const [plate, setPlate] = useState('BD51SMM')
    const [mousepricePostcode, setMousepricePostcode] = useState('SW1A 1AA')

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
        customer_reference: '', title_number: '',
        flat: '', house: '', street: '', town: '', postcode: '',
        order_register: true, order_title_plan: true
    })
    const updateLrData = (key, value) => setLrData(prev => ({ ...prev, [key]: value }))

    const [iduData, setIduData] = useState({
        forename: 'Michael', middlename: 'Stephen', surname: 'Smith',
        dd: '15', mm: '06', yyyy: '1992', gender: 'Male', reference: 'TEST_123',
        house: '', street: 'Denshaw Drive', town: 'Morley', postcode: 'LS27 8RR',
        email: '', email2: '', mobile: '', mobile2: '', landline: '', landline2: ''
    })
    const updateIduData = (key, value) => setIduData(prev => ({ ...prev, [key]: value }))

    const [iduSessionId, setIduSessionId] = useState(null)
    const [iduStatus, setIduStatus] = useState('idle') // idle | starting | awaiting_otp | processing | complete | error
    const [otpInput, setOtpInput] = useState('')
    const [childMaintenanceData, setChildMaintenanceData] = React.useState({
        role: 'paying',
        hasBenefits: false,
        benefits: [],
        hasIncome: false,
        income: '',
        income_frequency: 'monthly',
        add_parent_names: false,
        paying_parent_name: 'Alex',
        receiving_parent_name: 'Sam',
        child_name: 'Charlie',
        multiple_receiving_parents: false,
        other_children_in_home: 'None',
        receiving_parents: [{
            children_count: 1,
            children_names: [''],
            overnight_stays: 'never'
        }]
    })

    const updateChildData = (key, value) => {
        setChildMaintenanceData(prev => ({ ...prev, [key]: value }))
    }

    const toggleBenefit = (benefit) => {
        setChildMaintenanceData(prev => {
            if (benefit === 'None of these') {
                return { ...prev, benefits: prev.benefits.includes('None of these') ? [] : ['None of these'] }
            }
            const filtered = prev.benefits.filter(b => b !== 'None of these')
            return {
                ...prev,
                benefits: filtered.includes(benefit)
                    ? filtered.filter(b => b !== benefit)
                    : [...filtered, benefit]
            }
        })
    }

    const addParent = () => {
        setChildMaintenanceData(prev => {
            if (prev.receiving_parents.length >= 9) return prev
            const newParents = [
                ...prev.receiving_parents,
                { children_count: 1, children_names: [''], overnight_stays: 'never' }
            ]
            return { ...prev, receiving_parents: newParents }
        })
    }

    const removeParent = (parentIdx) => {
        setChildMaintenanceData(prev => {
            if (prev.receiving_parents.length === 1) return prev
            const newParents = prev.receiving_parents.filter((_, idx) => idx !== parentIdx)
            return { ...prev, receiving_parents: newParents }
        })
    }

    const updateParent = (parentIdx, key, value) => {
        setChildMaintenanceData(prev => ({
            ...prev,
            receiving_parents: prev.receiving_parents.map((parent, idx) => {
                if (idx !== parentIdx) return parent
                if (key === 'children_count') {
                    const count = Math.max(1, parseInt(value) || 1)
                    const names = [...parent.children_names]
                    while (names.length < count) names.push('')
                    while (names.length > count) names.pop()
                    return { ...parent, children_count: count, children_names: names }
                }
                return { ...parent, [key]: value }
            })
        }))
    }

    const updateChildName = (parentIdx, nameIdx, value) => {
        setChildMaintenanceData(prev => ({
            ...prev,
            receiving_parents: prev.receiving_parents.map((parent, idx) =>
                idx === parentIdx
                    ? { ...parent, children_names: parent.children_names.map((n, ni) => ni === nameIdx ? value : n) }
                    : parent
            )
        }))
    }

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
        setScrapeError('')

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
            if (activeTab === 'child-maintenance') {
                const isMultiple = childMaintenanceData.receiving_parents.length > 1;
                const parentsToSend = childMaintenanceData.receiving_parents;

                const payload = {
                    role: childMaintenanceData.role,
                    number_of_receiving_parents: parentsToSend.length,
                    benefits: childMaintenanceData.hasBenefits ? childMaintenanceData.benefits : [],
                    income: childMaintenanceData.hasIncome && childMaintenanceData.role === 'paying' ? Number(childMaintenanceData.income || 0) : null,
                    income_frequency: childMaintenanceData.income_frequency,
                    add_parent_names: childMaintenanceData.add_parent_names,
                    multiple_receiving_parents: childMaintenanceData.multiple_receiving_parents,
                    paying_parent_name: childMaintenanceData.paying_parent_name,
                    receiving_parent_name: childMaintenanceData.receiving_parent_name,
                    child_name: childMaintenanceData.child_name,
                    other_children_in_home: childMaintenanceData.other_children_in_home,
                    receiving_parents: parentsToSend.map(parent => ({
                        children_count: parent.children_count,
                        children_names: parent.children_names.filter(n => n.trim() !== ''),
                        overnight_stays: parent.overnight_stays
                    })),
                    headless: false // Added for debugging as requested
                }
                const response = await axios.post('/api/scrapers/child-maintenance', payload, {
                    headers: { 'Cache-Control': 'no-cache', 'Pragma': 'no-cache', 'Expires': '0' },
                    timeout: 120000
                })
                setResult(response.data)
                return
            }

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
            } else if (activeTab === 'mouseprice') {
                endpoint = `/api/scrapers/mouseprice?postcode=${mousepricePostcode}`
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
            setScrapeError(err.response?.data?.detail || err.message || 'Scraping failed')
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
                    { id: 'mouseprice', label: 'Mouseprice', icon: <Home size={18} /> },
                    { id: 'nationwide', label: 'Nationwide HPI', icon: <Home size={18} /> },
                    { id: 'lps', label: 'LPS Valuation', icon: <Building2 size={18} /> },
                    { id: 'landregistry', label: 'Land Registry', icon: <Building2 size={18} /> },
                    { id: 'child-maintenance', label: 'Child Maintenance', icon: <Scale size={18} /> },
                    { id: 'idu', label: 'IDU', icon: <UserCheck size={18} /> },
                ].map(tab => (
                    <button key={tab.id} className={`tab ${activeTab === tab.id ? 'active' : ''}`}
                        onClick={() => { setActiveTab(tab.id); setResult(null); setScrapeError(''); }}>
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

                    {activeTab === 'mouseprice' && (
                        <div className="form-group">
                            <label>Postcode</label>
                            <input type="text" className="input-field" value={mousepricePostcode} onChange={e => setMousepricePostcode(e.target.value.toUpperCase())} placeholder="e.g. SW1A 1AA" style={{ textTransform: 'uppercase' }} />
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

                    {activeTab === 'child-maintenance' && (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

                            {/* SECTION 1 — Basic Info */}
                            <div style={{ padding: 16, borderRadius: 10, background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}>
                                <p style={{ color: '#58a6ff', fontWeight: '600', marginBottom: 14, fontSize: '0.9rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Section 1 — Basic Info</p>
                                <div className="form-grid">
                                    <div className="form-group" style={{ gridColumn: 'span 2' }}>
                                        <label>Your Role</label>
                                        <select className="input-field" value={childMaintenanceData.role} onChange={e => {
                                            updateChildData('role', e.target.value);
                                            updateChildData('hasBenefits', false);
                                            updateChildData('benefits', []);
                                            updateChildData('moreThanOneParent', false);
                                        }}>
                                            <option value="paying">I am the Paying Parent</option>
                                            <option value="receiving">I am the Receiving Parent</option>
                                        </select>
                                    </div>
                                    
                                    {/* Role Specific */}
                                    {childMaintenanceData.role !== 'paying' && (
                                        <div className="form-group" style={{ gridColumn: 'span 2', marginTop: 10 }}>
                                            <label>Does the other parent get any benefits or State Pension?</label>
                                            <div style={{ display: 'flex', gap: 10, marginTop: 6 }}>
                                                <button type="button" className="tab" style={{ padding: '7px 18px', background: childMaintenanceData.hasBenefits ? 'var(--gradient)' : 'transparent', color: childMaintenanceData.hasBenefits ? '#fff' : 'var(--text-dim)', borderRadius: 8, border: '1px solid rgba(255,255,255,0.12)' }}
                                                    onClick={() => updateChildData('hasBenefits', true)}>Yes</button>
                                                <button type="button" className="tab" style={{ padding: '7px 18px', background: !childMaintenanceData.hasBenefits ? 'var(--gradient)' : 'transparent', color: !childMaintenanceData.hasBenefits ? '#fff' : 'var(--text-dim)', borderRadius: 8, border: '1px solid rgba(255,255,255,0.12)' }}
                                                    onClick={() => { updateChildData('hasBenefits', false); updateChildData('benefits', []); }}>No</button>
                                            </div>
                                        </div>
                                    )}
                                </div>

                                {/* Benefits toggle for Paying */}
                                {childMaintenanceData.role === 'paying' && (
                                    <div className="form-group" style={{ marginTop: 20 }}>
                                        <label>Do you get any benefits or State Pension?</label>
                                        <div style={{ display: 'flex', gap: 10, marginTop: 6 }}>
                                            <button type="button" className="tab" style={{ padding: '7px 18px', background: childMaintenanceData.hasBenefits ? 'var(--gradient)' : 'transparent', color: childMaintenanceData.hasBenefits ? '#fff' : 'var(--text-dim)', borderRadius: 8, border: '1px solid rgba(255,255,255,0.12)' }}
                                                onClick={() => updateChildData('hasBenefits', true)}>Yes</button>
                                            <button type="button" className="tab" style={{ padding: '7px 18px', background: !childMaintenanceData.hasBenefits ? 'var(--gradient)' : 'transparent', color: !childMaintenanceData.hasBenefits ? '#fff' : 'var(--text-dim)', borderRadius: 8, border: '1px solid rgba(255,255,255,0.12)' }}
                                                onClick={() => { updateChildData('hasBenefits', false); updateChildData('benefits', []); }}>No</button>
                                        </div>
                                    </div>
                                )}

                                {/* Shared Benefits Selector based on role check yes */}
                                <div style={{ maxHeight: childMaintenanceData.hasBenefits ? 1200 : 0, opacity: childMaintenanceData.hasBenefits ? 1 : 0, overflow: 'hidden', transition: 'all 0.3s ease' }}>
                                    <p style={{ color: 'var(--text-dim)', fontSize: '0.8rem', margin: '16px 0 8px' }}>Select all that apply:</p>
                                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, padding: '10px 0' }}>
                                        {[
                                            'Universal Credit',
                                            'Armed Forces Compensation Scheme payments',
                                            'Bereavement Allowance',
                                            'Carers Allowance/Carers Support Payment',
                                            'Incapacity Benefit',
                                            'Income Support',
                                            'Income-related Employment and Support Allowance',
                                            'Industrial Injuries Disablement Benefit',
                                            'Jobseeker’s Allowance – contribution-based',
                                            'Jobseeker’s Allowance – income-based',
                                            'Maternity Allowance',
                                            'Pension Credit',
                                            'Personal Independence Payment (PIP)',
                                            'Severe Disablement Allowance',
                                            'Skillseekers training',
                                            'State Pension',
                                            'Training Allowance',
                                            'War Disablement Pension',
                                            'War Widow’s, Widower’s or Surviving Civil Partner’s Pension',
                                            'Widow’s Pension',
                                            'Widowed Parent’s Allowance',
                                            'None of these'
                                        ].map(benefit => (
                                            <label key={benefit} style={{ display: 'flex', alignItems: 'flex-start', gap: 8, cursor: 'pointer', fontSize: '0.82rem', color: childMaintenanceData.benefits.includes(benefit) ? '#c9d1d9' : 'var(--text-dim)', padding: '6px 8px', borderRadius: 6, background: childMaintenanceData.benefits.includes(benefit) ? 'rgba(88,166,255,0.08)' : 'transparent', transition: 'all 0.15s' }}>
                                                <input type="checkbox" checked={childMaintenanceData.benefits.includes(benefit)} onChange={() => toggleBenefit(benefit)} style={{ accentColor: '#58a6ff', marginTop: 3 }} />
                                                <span style={{ lineHeight: 1.3 }}>{benefit}</span>
                                            </label>
                                        ))}
                                    </div>
                                </div>

                                {/* Income toggle (Paying Only) */}
                                {childMaintenanceData.role === 'paying' && (
                                    <>
                                        <div className="form-group" style={{ marginTop: 20 }}>
                                            <label>Do you receive any income?</label>
                                            <div style={{ display: 'flex', gap: 10, marginTop: 6 }}>
                                                <button type="button" className="tab" style={{ padding: '7px 18px', background: childMaintenanceData.hasIncome ? 'var(--gradient)' : 'transparent', color: childMaintenanceData.hasIncome ? '#fff' : 'var(--text-dim)', borderRadius: 8, border: '1px solid rgba(255,255,255,0.12)' }}
                                                    onClick={() => updateChildData('hasIncome', true)}>Yes</button>
                                                <button type="button" className="tab" style={{ padding: '7px 18px', background: !childMaintenanceData.hasIncome ? 'var(--gradient)' : 'transparent', color: !childMaintenanceData.hasIncome ? '#fff' : 'var(--text-dim)', borderRadius: 8, border: '1px solid rgba(255,255,255,0.12)' }}
                                                    onClick={() => updateChildData('hasIncome', false)}>No</button>
                                            </div>
                                        </div>

                                        <div style={{ maxHeight: childMaintenanceData.hasIncome ? 160 : 0, opacity: childMaintenanceData.hasIncome ? 1 : 0, overflow: 'hidden', transition: 'all 0.3s ease' }}>
                                            <div className="form-grid" style={{ marginTop: 12 }}>
                                                <div className="form-group">
                                                    <label>Income Amount (£)</label>
                                                    <input type="number" step="0.01" min="0" className="input-field" value={childMaintenanceData.income}
                                                        onChange={e => updateChildData('income', e.target.value)} />
                                                </div>
                                                <div className="form-group">
                                                    <label>Income Frequency</label>
                                                    <select className="input-field" value={childMaintenanceData.income_frequency}
                                                        onChange={e => updateChildData('income_frequency', e.target.value)}>
                                                        <option value="weekly">Weekly</option>
                                                        <option value="monthly">Monthly</option>
                                                        <option value="yearly">Yearly</option>
                                                    </select>
                                                </div>
                                            </div>
                                        </div>
                                    </>
                                )}
                            </div>

                            {/* SECTION 2 — Other Children & Personalisation */}
                            <div style={{ padding: 16, borderRadius: 10, background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}>
                                <p style={{ color: '#58a6ff', fontWeight: '600', marginBottom: 14, fontSize: '0.9rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Section 2 — House & Settings</p>
                                
                                <div className="form-group">
                                    <label>How many other children live with you? <span style={{ color: 'var(--text-dim)', fontWeight: 400 }}>(do not include any children you already pay child maintenance for)</span></label>
                                    <div style={{ display: 'flex', gap: 10, marginTop: 8, flexWrap: 'wrap' }}>
                                        {['None', '1', '2', '3 or more'].map(opt => (
                                            <button key={opt} type="button"
                                                style={{
                                                    padding: '8px 20px', borderRadius: 8, border: '1px solid rgba(255,255,255,0.12)',
                                                    cursor: 'pointer', fontSize: '0.85rem', fontWeight: '500', transition: 'all 0.15s',
                                                    background: childMaintenanceData.other_children_in_home === opt ? 'var(--gradient)' : 'transparent',
                                                    color: childMaintenanceData.other_children_in_home === opt ? '#fff' : 'var(--text-dim)'
                                                }}
                                                onClick={() => updateChildData('other_children_in_home', opt)}>
                                                {opt}
                                            </button>
                                        ))}
                                    </div>
                                </div>

                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, marginTop: 20 }}>
                                    <div className="form-group">
                                        <label>More than one other parent?</label>
                                        <div style={{ display: 'flex', gap: 10, marginTop: 6 }}>
                                            <button type="button" className="tab" style={{ padding: '7px 18px', background: childMaintenanceData.multiple_receiving_parents ? 'var(--gradient)' : 'transparent', color: childMaintenanceData.multiple_receiving_parents ? '#fff' : 'var(--text-dim)', borderRadius: 8, border: '1px solid rgba(255,255,255,0.12)' }}
                                                onClick={() => updateChildData('multiple_receiving_parents', true)}>Yes</button>
                                            <button type="button" className="tab" style={{ padding: '7px 18px', background: !childMaintenanceData.multiple_receiving_parents ? 'var(--gradient)' : 'transparent', color: !childMaintenanceData.multiple_receiving_parents ? '#fff' : 'var(--text-dim)', borderRadius: 8, border: '1px solid rgba(255,255,255,0.12)' }}
                                                onClick={() => updateChildData('multiple_receiving_parents', false)}>No</button>
                                        </div>
                                    </div>

                                    <div className="form-group">
                                        <label>Add parent names to calculation summary?</label>
                                        <div style={{ display: 'flex', gap: 10, marginTop: 6 }}>
                                            <button type="button" className="tab" style={{ padding: '7px 18px', background: childMaintenanceData.add_parent_names ? 'var(--gradient)' : 'transparent', color: childMaintenanceData.add_parent_names ? '#fff' : 'var(--text-dim)', borderRadius: 8, border: '1px solid rgba(255,255,255,0.12)' }}
                                                onClick={() => updateChildData('add_parent_names', true)}>Yes</button>
                                            <button type="button" className="tab" style={{ padding: '7px 18px', background: !childMaintenanceData.add_parent_names ? 'var(--gradient)' : 'transparent', color: !childMaintenanceData.add_parent_names ? '#fff' : 'var(--text-dim)', borderRadius: 8, border: '1px solid rgba(255,255,255,0.12)' }}
                                                onClick={() => updateChildData('add_parent_names', false)}>No</button>
                                        </div>
                                    </div>
                                </div>

                                {childMaintenanceData.add_parent_names && (
                                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12, marginTop: 16 }}>
                                        <div className="form-group">
                                            <label>Your Name</label>
                                            <input type="text" className="input-field" value={childMaintenanceData.paying_parent_name} 
                                                onChange={e => updateChildData('paying_parent_name', e.target.value)} />
                                        </div>
                                        <div className="form-group">
                                            <label>Other Parent's Name</label>
                                            <input type="text" className="input-field" value={childMaintenanceData.receiving_parent_name} 
                                                onChange={e => updateChildData('receiving_parent_name', e.target.value)} />
                                        </div>
                                        <div className="form-group">
                                            <label>Child's Name</label>
                                            <input type="text" className="input-field" value={childMaintenanceData.child_name} 
                                                onChange={e => {
                                                    const val = e.target.value;
                                                    updateChildData('child_name', val);
                                                    // Also update the first child of the first parent for consistency
                                                    if (childMaintenanceData.receiving_parents.length > 0) {
                                                        updateChildName(0, 0, val);
                                                    }
                                                }} />
                                        </div>
                                    </div>
                                )}
                            </div>

                            {/* SECTION 3 — Receiving Parents */}
                            <div style={{ padding: 16, borderRadius: 10, background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
                                    <p style={{ color: '#58a6ff', fontWeight: '600', fontSize: '0.9rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Section 3 — Receiving Parents</p>
                                    {(childMaintenanceData.role === 'paying') && (
                                        <button type="button" className="tab"
                                            style={{ padding: '8px 16px', display: 'flex', alignItems: 'center', gap: 6, borderRadius: 8, border: '1px solid rgba(255,255,255,0.15)', opacity: childMaintenanceData.receiving_parents.length >= 9 ? 0.4 : 1 }}
                                            onClick={addParent} disabled={childMaintenanceData.receiving_parents.length >= 9}>
                                            + Add Receiving Parent
                                        </button>
                                    )}
                                </div>

                                {childMaintenanceData.receiving_parents.map((parent, parentIdx) => (
                                    <div key={parentIdx} style={{ border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10, padding: 14, marginBottom: 14, background: 'rgba(0,0,0,0.15)', position: 'relative' }}>
                                        {/* Parent header */}
                                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                                <div style={{ width: 24, height: 24, borderRadius: '50%', background: 'var(--gradient)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.75rem', fontWeight: '700', color: '#fff' }}>
                                                    {parentIdx + 1}
                                                </div>
                                                <span style={{ fontWeight: '600', color: '#c9d1d9' }}>Receiving Parent {parentIdx + 1}</span>
                                            </div>
                                            {(childMaintenanceData.role === 'paying') && (
                                                <button type="button"
                                                    style={{ padding: '6px 14px', borderRadius: 8, border: '1px solid rgba(248,81,73,0.3)', background: 'rgba(248,81,73,0.08)', color: '#f85149', cursor: 'pointer', fontSize: '0.8rem', opacity: childMaintenanceData.receiving_parents.length === 1 ? 0.3 : 1 }}
                                                    onClick={() => removeParent(parentIdx)}
                                                    disabled={childMaintenanceData.receiving_parents.length === 1}>
                                                    Remove Parent
                                                </button>
                                            )}
                                        </div>

                                        <div className="form-grid">
                                            {/* Children count */}
                                            <div className="form-group">
                                                <label>Number of Children</label>
                                                <input type="number" min="1" max="20" className="input-field"
                                                    value={parent.children_count}
                                                    onChange={e => updateParent(parentIdx, 'children_count', e.target.value)} />
                                            </div>

                                            {/* Overnight stays — per parent block */}
                                            <div className="form-group">
                                                <label>Overnight Stays (nights/year)</label>
                                                <select className="input-field" value={parent.overnight_stays}
                                                    onChange={e => updateParent(parentIdx, 'overnight_stays', e.target.value)}>
                                                    <option value="never">Never</option>
                                                    <option value="up-to-52">Up to 1 night a week (fewer than 52 nights a year)</option>
                                                    <option value="52-103">1 to 2 nights a week (52 to 103 nights a year)</option>
                                                    <option value="104-155">2 to 3 nights a week (104 to 155 nights a year)</option>
                                                    <option value="156-174">More than 3 nights a week - but not half the time (156 to 174 nights a year)</option>
                                                    <option value="175-182">Half the time (175 to 182 nights a year)</option>
                                                </select>
                                            </div>
                                        </div>

                                        {/* Children names */}
                                        {parent.children_names.length > 0 && (
                                            <div style={{ marginTop: 12 }}>
                                                <label style={{ display: 'block', marginBottom: 8, color: 'var(--text-dim)', fontSize: '0.82rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Children's Names</label>
                                                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                                                    {parent.children_names.map((name, nameIdx) => (
                                                        <div key={nameIdx} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                                            <span style={{ color: 'var(--text-dim)', fontSize: '0.78rem', minWidth: 60 }}>Child {nameIdx + 1}</span>
                                                            <input
                                                                type="text" className="input-field"
                                                                style={{ flex: 1 }}
                                                                placeholder={`Child ${nameIdx + 1} name (optional)`}
                                                                value={name}
                                                                onChange={e => updateChildName(parentIdx, nameIdx, e.target.value)}
                                                            />
                                                        </div>
                                                    ))}
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                ))}
                            </div>

                        </div>
                    )}

                    <button className="submit-btn" disabled={loading || iduStatus === 'awaiting_otp'}>
                        {loading ? (
                            <div style={{ display: 'flex', alignItems: 'center', gap: 10, justifyContent: 'center' }}>
                                <span className="loading-spinner"></span>
                                <span>
                                    {iduStatus === 'starting' ? 'Initializing IDU...' : 
                                     iduStatus === 'processing' ? 'Processing Search...' : 
                                     activeTab === 'child-maintenance' ? 'Running Calculation...' :
                                     'Running Scraper...'}
                                </span>
                            </div>
                        ) : activeTab === 'child-maintenance' ? 'Run Calculation' : 'Run Scraper'}
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

                {scrapeError && (
                    <div style={{
                        marginTop: 16,
                        padding: 14,
                        background: 'rgba(248,81,73,0.1)',
                        border: '1px solid rgba(248,81,73,0.3)',
                        borderRadius: 10,
                        color: '#f85149',
                        fontSize: '0.9rem'
                    }}>
                        {scrapeError}
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

                        {activeTab === 'mouseprice' && (
                            <div>
                                {/* FAILURE STATE — amber card for no data / no results / parse error */}
                                {!result.parse_success && (
                                    <div style={{ textAlign: 'center', padding: '32px 16px', background: 'rgba(246,185,59,0.06)', border: '1px solid rgba(246,185,59,0.25)', borderRadius: 10, marginBottom: 16 }}>
                                        <div style={{ fontSize: '3rem', marginBottom: 12 }}>🏚️</div>
                                        <h3 style={{ color: '#f6b93b', fontWeight: '700', fontSize: '1.15rem', marginBottom: 10 }}>
                                            No Property Data Found for {result.postcode}
                                        </h3>
                                        <p style={{ color: '#c9d1d9', fontSize: '0.875rem', lineHeight: '1.7', maxWidth: 520, margin: '0 auto' }}>
                                            {result.no_results_reason ||
                                                'No property sales data was found for this postcode. This usually means it is a non-residential address (e.g. government, royal, or commercial) with no recorded transactions, or the postcode is too new / too rural to have sales history on Mouseprice.'}
                                        </p>
                                        {result.url && (
                                            <a href={result.url} target="_blank" rel="noreferrer"
                                                style={{ display: 'inline-block', marginTop: 16, fontSize: '0.8rem', color: '#58a6ff' }}>
                                                View on Mouseprice ↗
                                            </a>
                                        )}
                                    </div>
                                )}



                                {/* SUCCESS STATE */}
                                {result.parse_success && (
                                    <>
                                        <table>
                                            <thead><tr><th>Postcode</th><th>Average Price</th><th>No. of Sales</th><th>Avg £/sqm</th></tr></thead>
                                            <tbody>
                                                <tr>
                                                    <td>{result.postcode}</td>
                                                    <td style={{ color: '#56d364', fontWeight: 'bold' }}>{result.average_price}</td>
                                                    <td>{result.number_of_sales}</td>
                                                    <td>{result.avg_psqm}</td>
                                                </tr>
                                            </tbody>
                                        </table>

                                        <ScreenshotPreview url={result.screenshot_url} />
                                    </>
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

                        {activeTab === 'child-maintenance' && (
                            <div>
                                {/* Main result — big highlight card */}
                                <div style={{ padding: 20, borderRadius: 12, background: 'linear-gradient(135deg, rgba(88,166,255,0.12), rgba(150,70,255,0.08))', border: '1px solid rgba(88,166,255,0.25)', marginBottom: 16, textAlign: 'center' }}>
                                    <p style={{ color: '#8b949e', fontSize: '0.8rem', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8 }}>Calculation Result</p>
                                    <p style={{ color: '#58a6ff', fontWeight: '700', fontSize: '1.6rem', lineHeight: 1.3 }}>{result.result || 'No result returned'}</p>
                                </div>

                                {result.reason && (
                                    <div style={{ padding: 16, borderRadius: 10, background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', marginBottom: 14 }}>
                                        <p style={{ color: '#8b949e', fontSize: '0.8rem', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>Breakdown / Reason</p>
                                        <p style={{ color: '#c9d1d9', lineHeight: 1.7, fontSize: '0.9rem' }}>{result.reason}</p>
                                    </div>
                                )}

                                {result.pdf_url && (
                                    <a 
                                        href={result.pdf_url} 
                                        target="_blank" 
                                        rel="noopener noreferrer"
                                        className="download-btn"
                                        style={{ 
                                            display: 'inline-flex', 
                                            alignItems: 'center', 
                                            gap: 8, 
                                            background: '#1f6feb', 
                                            color: '#fff', 
                                            padding: '10px 20px', 
                                            borderRadius: 8, 
                                            textDecoration: 'none', 
                                            fontSize: '0.88rem',
                                            fontWeight: '600',
                                            marginBottom: 16,
                                            transition: 'background 0.2s'
                                        }}
                                        onMouseOver={e => e.currentTarget.style.background = '#388bfd'}
                                        onMouseOut={e => e.currentTarget.style.background = '#1f6feb'}
                                    >
                                        📄 Download Calculation PDF
                                    </a>
                                )}

                                {/* Error card */}
                                {result.error && (
                                    <div style={{ padding: 14, borderRadius: 10, background: 'rgba(248,81,73,0.1)', border: '1px solid rgba(248,81,73,0.3)', color: '#f85149', marginBottom: 14, display: 'flex', alignItems: 'flex-start', gap: 10 }}>
                                        <span style={{ fontSize: '1rem' }}>⚠️</span>
                                        <span style={{ fontSize: '0.88rem', lineHeight: 1.6 }}>{result.error}</span>
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