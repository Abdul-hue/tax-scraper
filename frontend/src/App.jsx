import React, { useState } from 'react'
import axios from 'axios'
import { Calculator, MapPin, Loader2, Camera, ExternalLink, Settings2, Car } from 'lucide-react'

function App() {
    const [activeTab, setActiveTab] = useState('taxman')
    const [loading, setLoading] = useState(false)
    const [result, setResult] = useState(null)

    // Taxman Form States
    const [taxData, setTaxData] = useState({
        salary: 3000,
        period: 'month',
        tax_year: '2025/26',
        region: 'UK',
        age: 'under 65',
        student_loan: 'No',
        pension_amount: 0,
        pension_type: '£',
        allowances: 0,
        tax_code: '',
        married: false,
        blind: false,
        no_ni: false
    })

    // Council Form State
    const [postcode, setPostcode] = useState('LS278RR')

    // Parkers Form State
    const [plate, setPlate] = useState('BD51SMM')

    const handleScrape = async (e) => {
        e.preventDefault()
        setLoading(true)
        setResult(null)

        try {
            let endpoint = ''
            if (activeTab === 'taxman') {
                const params = new URLSearchParams(taxData)
                endpoint = `/api/scrapers/taxman?${params.toString()}`
            } else if (activeTab === 'council') {
                endpoint = `/api/scrapers/counciltax?postcode=${postcode}`
            } else if (activeTab === 'parkers') {
                endpoint = `/api/scrapers/parkers?plate=${plate}`
            }

            const response = await axios.get(endpoint)
            setResult(response.data)
        } catch (err) {
            alert("Scraping failed: " + (err.response?.data?.detail || err.message))
        } finally {
            setLoading(false)
        }
    }

    const updateTaxData = (key, value) => {
        setTaxData(prev => ({ ...prev, [key]: value }))
    }

    return (
        <div className="app-container">
            <h1>Scraper API Control</h1>

            <div className="tabs-container">
                <button
                    className={`tab ${activeTab === 'taxman' ? 'active' : ''}`}
                    onClick={() => { setActiveTab('taxman'); setResult(null); }}
                >
                    <Calculator size={18} style={{ marginRight: 8, verticalAlign: 'middle' }} />
                    Listen To Taxman
                </button>
                <button
                    className={`tab ${activeTab === 'council' ? 'active' : ''}`}
                    onClick={() => { setActiveTab('council'); setResult(null); }}
                >
                    <MapPin size={18} style={{ marginRight: 8, verticalAlign: 'middle' }} />
                    Council Tax
                </button>
                <button
                    className={`tab ${activeTab === 'parkers' ? 'active' : ''}`}
                    onClick={() => { setActiveTab('parkers'); setResult(null); }}
                >
                    <Car size={18} style={{ marginRight: 8, verticalAlign: 'middle' }} />
                    Parkers
                </button>
            </div>

            <div className="form-card">
                <form onSubmit={handleScrape}>
                    {activeTab === 'taxman' && (
                        <div className="form-grid">
                            <div className="form-group">
                                <label>Salary Amount</label>
                                <input
                                    type="number"
                                    className="input-field"
                                    value={taxData.salary}
                                    onChange={(e) => updateTaxData('salary', e.target.value)}
                                />
                            </div>
                            <div className="form-group">
                                <label>Salary Period</label>
                                <select
                                    className="input-field"
                                    value={taxData.period}
                                    onChange={(e) => updateTaxData('period', e.target.value)}
                                >
                                    <option value="year">Yearly</option>
                                    <option value="month">Monthly</option>
                                    <option value="4weeks">4 Weekly</option>
                                    <option value="week">Weekly</option>
                                    <option value="day">Daily</option>
                                    <option value="hour">Hourly</option>
                                </select>
                            </div>
                            <div className="form-group">
                                <label>Tax Year</label>
                                <select
                                    className="input-field"
                                    value={taxData.tax_year}
                                    onChange={(e) => updateTaxData('tax_year', e.target.value)}
                                >
                                    <option value="2025/26">2025/26</option>
                                    <option value="2024/25">2024/25</option>
                                    <option value="2023/24">2023/24</option>
                                </select>
                            </div>
                            <div className="form-group">
                                <label>Region</label>
                                <select
                                    className="input-field"
                                    value={taxData.region}
                                    onChange={(e) => updateTaxData('region', e.target.value)}
                                >
                                    <option value="UK">UK (England, NI, Wales)</option>
                                    <option value="Scotland">Scotland</option>
                                </select>
                            </div>
                            <div className="form-group">
                                <label>Pension Contribution</label>
                                <div style={{ display: 'flex', gap: 5 }}>
                                    <input
                                        type="number"
                                        className="input-field"
                                        style={{ flex: 1 }}
                                        value={taxData.pension_amount}
                                        onChange={(e) => updateTaxData('pension_amount', e.target.value)}
                                    />
                                    <select
                                        className="input-field"
                                        style={{ width: 60 }}
                                        value={taxData.pension_type}
                                        onChange={(e) => updateTaxData('pension_type', e.target.value)}
                                    >
                                        <option value="£">£</option>
                                        <option value="%">%</option>
                                    </select>
                                </div>
                            </div>
                            <div className="form-group">
                                <label>Additional Allowances (£)</label>
                                <input
                                    type="number"
                                    className="input-field"
                                    value={taxData.allowances}
                                    onChange={(e) => updateTaxData('allowances', e.target.value)}
                                />
                            </div>
                            <div className="form-group">
                                <label>Tax Code (Optional)</label>
                                <input
                                    type="text"
                                    className="input-field"
                                    value={taxData.tax_code}
                                    onChange={(e) => updateTaxData('tax_code', e.target.value)}
                                    placeholder="e.g. 1257L"
                                />
                            </div>
                            <div className="form-group">
                                <label>Student Loan</label>
                                <select
                                    className="input-field"
                                    value={taxData.student_loan}
                                    onChange={(e) => updateTaxData('student_loan', e.target.value)}
                                >
                                    <option value="No">No Student Loan</option>
                                    <option value="Plan 1">Plan 1</option>
                                    <option value="Plan 2">Plan 2</option>
                                    <option value="Plan 4">Plan 4 (Scottish)</option>
                                    <option value="Postgraduate">Postgraduate</option>
                                </select>
                            </div>

                            <div className="form-group checkbox-group" style={{ gridColumn: 'span 2' }}>
                                <label style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer' }}>
                                    <input type="checkbox" checked={taxData.married} onChange={(e) => updateTaxData('married', e.target.checked)} />
                                    Married Allowance
                                </label>
                                <label style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer' }}>
                                    <input type="checkbox" checked={taxData.blind} onChange={(e) => updateTaxData('blind', e.target.checked)} />
                                    Blind Allowance
                                </label>
                                <label style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer' }}>
                                    <input type="checkbox" checked={taxData.no_ni} onChange={(e) => updateTaxData('no_ni', e.target.checked)} />
                                    Exempt from NI
                                </label>
                            </div>
                        </div>
                    )}

                    {activeTab === 'council' && (
                        <div className="form-group">
                            <label>Postcode</label>
                            <input
                                type="text"
                                className="input-field"
                                value={postcode}
                                onChange={(e) => setPostcode(e.target.value)}
                                placeholder="e.g. SW1A 1AA"
                            />
                        </div>
                    )}

                    {activeTab === 'parkers' && (
                        <div className="form-group">
                            <label>Car Registration Plate</label>
                            <input
                                type="text"
                                className="input-field"
                                value={plate}
                                onChange={(e) => setPlate(e.target.value)}
                                placeholder="e.g. BD51 SMM"
                                style={{ textTransform: 'uppercase' }}
                            />
                        </div>
                    )}

                    <button className="submit-btn" disabled={loading}>
                        {loading ? (
                            <span className="loading-spinner"></span>
                        ) : (
                            'Run Scraper'
                        )}
                    </button>
                </form>
            </div>

            {result && (
                <div className="results-container">
                    <div className="data-card">
                        <h3 style={{ marginBottom: 20, display: 'flex', alignItems: 'center', gap: 10 }}>
                            <ExternalLink size={20} color="#58a6ff" />
                            Scraped Data
                        </h3>

                        {activeTab === 'taxman' && (
                            <table>
                                <thead>
                                    <tr>
                                        <th>Label</th>
                                        <th>Yearly</th>
                                        <th>Monthly</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {result.payslip?.slice(1).map((row, idx) => (
                                        <tr key={idx}>
                                            <td>{row.label}</td>
                                            <td>{row.yearly}</td>
                                            <td style={{ color: row.label === 'Net Wage' ? '#58a6ff' : '' }}>{row.monthly}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        )}

                        {activeTab === 'council' && (
                            <table>
                                <thead>
                                    <tr>
                                        <th>Address</th>
                                        <th>Band</th>
                                        <th>Monthly</th>
                                    </tr>
                                </thead>
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
                        )}

                        {activeTab === 'parkers' && (
                            <div>
                                <div style={{ marginBottom: 20, padding: 15, background: 'rgba(255,255,255,0.05)', borderRadius: 10 }}>
                                    <p style={{ color: '#8b949e', fontSize: '0.9rem' }}>Vehicle Identified:</p>
                                    <p style={{ fontSize: '1.2rem', fontWeight: 'bold', color: '#58a6ff' }}>
                                        {result.make} {result.model} {result.year}
                                    </p>
                                    <p style={{ fontSize: '0.8rem', color: '#8b949e', marginTop: 5 }}>Plate: {result.reg_plate}</p>
                                </div>
                                <table>
                                    <thead>
                                        <tr>
                                            <th>Condition</th>
                                            <th>Price Range</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        <tr>
                                            <td>Private Sale</td>
                                            <td style={{ fontWeight: '600', color: '#9646ff' }}>
                                                {result.prices?.private_low} - {result.prices?.private_high}
                                            </td>
                                        </tr>
                                        <tr>
                                            <td>Dealer / Forecourt</td>
                                            <td style={{ fontWeight: '600', color: '#58a6ff' }}>
                                                {result.prices?.dealer_low} - {result.prices?.dealer_high}
                                            </td>
                                        </tr>
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </div>

                    {result.screenshot_path && (
                        <div className="screenshot-card">
                            <h3 style={{ padding: '15px 15px 5px', display: 'flex', alignItems: 'center', gap: 10, fontSize: '1rem' }}>
                                <Camera size={18} color="#58a6ff" />
                                Live Result Screenshot
                            </h3>
                            <a href={result.screenshot_path} target="_blank" rel="noreferrer">
                                <img
                                    src={result.screenshot_path}
                                    alt="Scraper Screenshot"
                                />
                            </a>
                            <p style={{ padding: 15, fontSize: '0.8rem', color: '#8b949e' }}>
                                Click image to open full resolution
                            </p>
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}

export default App
